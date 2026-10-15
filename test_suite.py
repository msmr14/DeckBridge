import os
import tempfile
import unittest

# Ensure headless offscreen platform for Qt tests
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from unittest.mock import patch, MagicMock

import vdf
from steam_syncer import (
    clean_game_name,
    is_valid_executable,
    calculate_steam_ids,
    backup_shortcuts_file,
    load_shortcuts_vdf,
    save_shortcuts_vdf,
    add_games_to_shortcuts,
    verify_shortcuts_integrity,
    find_best_game_exe,
    parse_folder_list,
    search_steam_store_appid,
    search_steam_store,
    run_synchronization,
    safe_requests_get,
    download_artwork_for_game,
    download_artwork,
    download_game_artwork,
    fetch_appdetails_assets,
    get_steam_users_info,
    is_safe_valve_url,
    is_safe_grid_path,
    is_safe_steam_user_id,
    close_steam_client,
    get_available_drives,
    get_default_game_folders,
    scan_games
)


class TestSteamSyncer(unittest.TestCase):

    def test_clean_game_name(self):
        cases = [
            ("Hades-Standalone", "Hades"),
            ("OpenTTD [Portable]", "OpenTTD"),
            ("SuperTux.Deluxe-DRMFree", "SuperTux Deluxe"),
            ("Cyberpunk.2077.Digital.Deluxe-GOG", "Cyberpunk 2077 Digital Deluxe"),
            ("It Takes Two", "It Takes Two"),
            ("[GOG] Cyberpunk 2077 v2.12", "Cyberpunk 2077"),
            ("The.Witcher.3.Wild.Hunt.[DRM-Free].Build.4567", "The Witcher 3 Wild Hunt"),
            ("Elden Ring (Portable) v1.12.1", "Elden Ring"),
            ("Baldurs.Gate.3.Digital.Deluxe.Edition-GOG", "Baldurs Gate 3 Digital Deluxe Edition"),
            ("Red Dead Redemption 2 - Ultimate Edition (v1491.50)", "Red Dead Redemption 2 - Ultimate Edition"),
            ("Forza Horizon 5 Premium Edition v 1.634.488.0 [Archive]", "Forza Horizon 5 Premium Edition")
        ]
        for raw, expected in cases:
            self.assertEqual(clean_game_name(raw), expected)

    def test_parse_folder_list(self):
        # Space-separated composite string (from original task: 'D:\Gamess C:\Games')
        res = parse_folder_list("D:\\Gamess C:\\Games")
        self.assertEqual(res, ["D:\\Gamess", "C:\\Games"])

        # Semicolon-separated
        res = parse_folder_list("D:\\Gamess;C:\\Games")
        self.assertEqual(res, ["D:\\Gamess", "C:\\Games"])

        # List with composite element
        res = parse_folder_list(["D:\\Gamess C:\\Games"])
        self.assertEqual(res, ["D:\\Gamess", "C:\\Games"])

        # List of normal paths
        res = parse_folder_list(["D:\\Gamess", "C:\\Games"])
        self.assertEqual(res, ["D:\\Gamess", "C:\\Games"])

    def test_is_valid_executable(self):
        invalid_exes = [
            "unins000.exe", "CrashReport.exe", "BugSplatHD64.exe",
            "UnityCrashHandler64.exe", "DXSETUP.exe", "EasyAntiCheat_Setup.exe",
            "eac_server.exe", "redist_x64.exe", "Touchup.exe", "Cleanup.exe",
            "EpicWebHelper.exe", "crs-handler.exe", "crs-video.exe"
        ]
        for name in invalid_exes:
            self.assertFalse(is_valid_executable(name), f"Should be invalid: {name}")

        valid_exes = [
            "Spider-Man.exe", "KingdomCome.exe", "ItTakesTwo.exe", "game.exe",
            "Hades.exe", "Portal2.exe", "OpenTTD.exe",
            "CrashBandicoot4.exe", "Crash.exe"
        ]
        for name in valid_exes:
            self.assertTrue(is_valid_executable(name), f"Should be valid: {name}")

        self.assertTrue(is_valid_executable("Crash.exe", clean_name="Crash Bandicoot"))
        self.assertFalse(is_valid_executable("CrashReporter.exe", clean_name="Crash Bandicoot"))

    def test_calculate_steam_ids(self):
        exe = r"C:\Games\Test\test.exe"
        name = "Test Game"
        grid_id, vdf_appid, grid_id_64 = calculate_steam_ids(exe, name)

        # Grid ID must have top bit set
        self.assertTrue(bool(grid_id & 0x80000000))
        # vdf_appid must be within 32-bit signed range
        self.assertGreaterEqual(vdf_appid, -2147483648)
        self.assertLessEqual(vdf_appid, 2147483647)
        # grid_id_64 must be constructed from (grid_id << 32) | 0x02000000
        self.assertEqual(grid_id_64, (grid_id << 32) | 0x02000000)

        # Quoted exe input should yield identical IDs as unquoted
        grid_id_q, vdf_appid_q, grid_id_64_q = calculate_steam_ids(f'"{exe}"', name)
        self.assertEqual(grid_id, grid_id_q)
        self.assertEqual(vdf_appid, vdf_appid_q)
        self.assertEqual(grid_id_64, grid_id_64_q)

    def test_find_best_game_exe_prioritizes_root_exact_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create root launcher
            root_exe = os.path.join(tmpdir, "inZOI.exe")
            with open(root_exe, 'wb') as f:
                f.write(b'\x00' * 500)

            # Create shipping subfolder binary with larger size
            sub_dir = os.path.join(tmpdir, "BlueClient", "Binaries", "Win64")
            os.makedirs(sub_dir, exist_ok=True)
            shipping_exe = os.path.join(sub_dir, "inZOI-Win64-Shipping.exe")
            with open(shipping_exe, 'wb') as f:
                f.write(b'\x00' * 50000)

            best = find_best_game_exe(tmpdir, "inZOI")
            self.assertIsNotNone(best)
            # Must prioritize root launcher
            self.assertEqual(best['name'], "inZOI.exe")

    def test_shortcuts_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vdf_path = os.path.join(tmpdir, "shortcuts.vdf")
            initial_data = {
                'shortcuts': {
                    '0': {
                        'appid': -123456,
                        'AppName': 'Demo Game',
                        'Exe': '"C:\\test\\demo.exe"',
                        'StartDir': '"C:\\test"',
                        'icon': '',
                        'ShortcutPath': '',
                        'LaunchOptions': '',
                        'IsHidden': 0,
                        'AllowDesktopConfig': 1,
                        'AllowOverlay': 1,
                        'OpenVR': 0,
                        'Devkit': 0,
                        'DevkitGameID': '',
                        'DevkitOverrideAppId': 0,
                        'LastPlayTime': 0,
                        'FlatpakAppID': '',
                        'tags': {}
                    }
                }
            }
            save_shortcuts_vdf(vdf_path, initial_data)
            self.assertTrue(os.path.exists(vdf_path))

            # Backup
            bak = backup_shortcuts_file(vdf_path)
            self.assertIsNotNone(bak)
            self.assertTrue(os.path.exists(vdf_path + ".bak"))

            # Load back
            loaded = load_shortcuts_vdf(vdf_path)
            self.assertIn('shortcuts', loaded)
            self.assertEqual(loaded['shortcuts']['0']['AppName'], 'Demo Game')

            # Verification check
            ok, msg = verify_shortcuts_integrity(vdf_path)
            self.assertTrue(ok, msg)

    def test_duplicate_prevention(self):
        with patch('steam_syncer.is_steam_running', return_value=False):
            with tempfile.TemporaryDirectory() as tmpdir:
                vdf_path = os.path.join(tmpdir, "shortcuts.vdf")
                save_shortcuts_vdf(vdf_path, {'shortcuts': {}})

                game = {
                    'clean_name': 'My Game',
                    'folder_path': os.path.join(tmpdir, 'MyGame'),
                    'exe_path': os.path.join(tmpdir, 'MyGame', 'game.exe')
                }

                # First add
                added, _ = add_games_to_shortcuts(vdf_path, [game], download_artwork=False)
                self.assertEqual(added, 1)

                # Second add (duplicate)
                added_dup, _ = add_games_to_shortcuts(vdf_path, [game], download_artwork=False)
                self.assertEqual(added_dup, 0)

                # Verify count in VDF
                loaded = load_shortcuts_vdf(vdf_path)
                self.assertEqual(len(loaded['shortcuts']), 1)

    def test_steam_running_guard(self):
        with patch('steam_syncer.is_steam_running', return_value=True):
            report = run_synchronization(game_folders=[r"C:\Games"])
            self.assertTrue(report['steam_running'])
            self.assertFalse(report['success'])
            self.assertIn("RUNNING", report['message'])

    def test_store_search_filters_soundtracks_and_dlc(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'total': 2,
            'items': [
                {'id': 999999, 'name': 'The Witcher 3: Wild Hunt - Soundtrack'},
                {'id': 292030, 'name': 'The Witcher 3: Wild Hunt'}
            ]
        }
        with patch('requests.get', return_value=mock_resp):
            appid = search_steam_store_appid("The Witcher 3: Wild Hunt")
            self.assertEqual(appid, 292030)

    def test_load_shortcuts_vdf_zero_byte(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_vdf = os.path.join(tmpdir, "shortcuts.vdf")
            with open(empty_vdf, "wb") as f:
                f.write(b"")
            res = load_shortcuts_vdf(empty_vdf)
            self.assertEqual(res, {'shortcuts': {}})

    def test_load_shortcuts_vdf_corrupt_binary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            corrupt_vdf = os.path.join(tmpdir, "shortcuts.vdf")
            with open(corrupt_vdf, "wb") as f:
                f.write(b"\xFF\xFE\x00\x12\x34GarbageBinaryContentThatIsNotVDF\x00\x00")
            res = load_shortcuts_vdf(corrupt_vdf)
            self.assertEqual(res, {'shortcuts': {}})

    def test_backup_shortcuts_file_skips_zero_byte(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vdf_path = os.path.join(tmpdir, "shortcuts.vdf")
            bak_path = vdf_path + ".bak"
            with open(bak_path, "wb") as f:
                f.write(b"ExistingValidBackupContent")
            with open(vdf_path, "wb") as f:
                f.write(b"")

            res = backup_shortcuts_file(vdf_path)
            self.assertIsNone(res)
            with open(bak_path, "rb") as f:
                content = f.read()
            self.assertEqual(content, b"ExistingValidBackupContent")

    def test_safe_requests_resilience(self):
        import socket
        import requests
        with patch('requests.get', side_effect=requests.exceptions.Timeout("Connection timed out")):
            res = safe_requests_get("https://invalid-steam-url.test", max_retries=1)
            self.assertIsNone(res)

        with patch('requests.get', side_effect=socket.gaierror("DNS failed")):
            res = safe_requests_get("https://invalid-steam-url.test", max_retries=1)
            self.assertIsNone(res)

        with patch('requests.get', side_effect=requests.exceptions.SSLError("SSL verification failed")):
            res = safe_requests_get("https://invalid-steam-url.test", max_retries=1)
            self.assertIsNone(res)

    def test_add_games_with_quoted_and_unicode_paths(self):
        with patch('steam_syncer.is_steam_running', return_value=False):
            with tempfile.TemporaryDirectory() as tmpdir:
                vdf_path = os.path.join(tmpdir, "shortcuts.vdf")
                save_shortcuts_vdf(vdf_path, {'shortcuts': {}})

                game = {
                    'clean_name': 'Ведьмак 3: Дикая Охота',
                    'folder_path': os.path.join(tmpdir, 'Ведьмак 3'),
                    'exe_path': f'"{os.path.join(tmpdir, "Ведьмак 3", "witcher3.exe")}"'
                }

                added, _ = add_games_to_shortcuts(vdf_path, [game], download_artwork=False)
                self.assertEqual(added, 1)

                loaded = load_shortcuts_vdf(vdf_path)
                entry = loaded['shortcuts']['0']
                self.assertFalse(entry['Exe'].startswith('""'))
                self.assertTrue(entry['Exe'].startswith('"') and entry['Exe'].endswith('"'))
                self.assertIn("witcher3.exe", entry['Exe'])
                self.assertEqual(entry['AppName'], 'Ведьмак 3: Дикая Охота')

                dup_game = {
                    'clean_name': 'Ведьмак 3: Дикая Охота',
                    'folder_path': os.path.join(tmpdir, 'Ведьмак 3'),
                    'exe_path': os.path.join(tmpdir, 'Ведьмак 3', 'witcher3.exe')
                }
                added_dup, _ = add_games_to_shortcuts(vdf_path, [dup_game], download_artwork=False)
                self.assertEqual(added_dup, 0)

    def test_download_artwork_alias(self):
        self.assertIs(download_artwork, download_artwork_for_game)
        self.assertIs(download_game_artwork, download_artwork_for_game)
        self.assertIs(search_steam_store, search_steam_store_appid)

    def test_search_steam_store_edge_cases(self):
        # None, empty, whitespace must return None immediately without exception
        self.assertIsNone(search_steam_store_appid(None))
        self.assertIsNone(search_steam_store_appid(""))
        self.assertIsNone(search_steam_store_appid("   "))

        # Malformed JSON / unexpected items
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'items': [
                "not-a-dict",
                {'id': None, 'name': 'Bad App'},
                {'id': 'not-an-int', 'name': 'Invalid ID'},
                {'id': 12345, 'name': 'Valid Game'}
            ]
        }
        with patch('requests.get', return_value=mock_resp):
            res = search_steam_store_appid("Valid Game")
            self.assertEqual(res, 12345)

    def test_fetch_appdetails_assets_edge_cases(self):
        self.assertEqual(fetch_appdetails_assets(None), {})
        self.assertEqual(fetch_appdetails_assets(-1), {})
        self.assertEqual(fetch_appdetails_assets(0), {})

        # API returns null or false for appid
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'123': None}
        with patch('requests.get', return_value=mock_resp):
            self.assertEqual(fetch_appdetails_assets(123), {})

        mock_resp.json.return_value = {'123': {'success': False}}
        with patch('requests.get', return_value=mock_resp):
            self.assertEqual(fetch_appdetails_assets(123), {})

    def test_clean_game_name_tag_only_fallback(self):
        # If folder consists only of stripped tags, it must not return an empty string
        res = clean_game_name("[Portable]")
        self.assertTrue(len(res) > 0)
        self.assertEqual(res, "[Portable]")

        res2 = clean_game_name("[GOG]")
        self.assertTrue(len(res2) > 0)
        self.assertEqual(res2, "[GOG]")

    def test_loginusers_case_insensitivity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = os.path.join(tmpdir, "config")
            account_id = "99999999"
            steamid64 = str(76561197960265728 + int(account_id))
            userdata_dir = os.path.join(tmpdir, "userdata", account_id)
            os.makedirs(config_dir, exist_ok=True)
            os.makedirs(userdata_dir, exist_ok=True)

            # loginusers.vdf with capitalized "Users" root key
            loginusers_vdf = (
                f'"Users"\n'
                f'{{\n'
                f'    "{steamid64}"\n'
                f'    {{\n'
                f'        "AccountName" "capital_user"\n'
                f'        "PersonaName" "CaptainCapital"\n'
                f'        "MostRecent" "1"\n'
                f'        "Timestamp" "1710000000"\n'
                f'    }}\n'
                f'}}\n'
            )
            with open(os.path.join(config_dir, "loginusers.vdf"), 'w', encoding='utf-8') as f:
                f.write(loginusers_vdf)

            users = get_steam_users_info(tmpdir)
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0]['persona_name'], 'CaptainCapital')
            self.assertTrue(users[0]['is_active'])

    def test_forward_slash_normalization(self):
        with patch('steam_syncer.is_steam_running', return_value=False):
            with tempfile.TemporaryDirectory() as tmpdir:
                vdf_path = os.path.join(tmpdir, "shortcuts.vdf")
                save_shortcuts_vdf(vdf_path, {'shortcuts': {}})

                # Executable with forward slashes
                game = {
                    'clean_name': 'Slash Game',
                    'folder_path': tmpdir + "/SlashGame",
                    'exe_path': tmpdir + "/SlashGame/slash.exe"
                }
                added, _ = add_games_to_shortcuts(vdf_path, [game], download_artwork=False)
                self.assertEqual(added, 1)

                loaded = load_shortcuts_vdf(vdf_path)
                entry = loaded['shortcuts']['0']
                # Must not contain forward slashes in Windows shortcuts.vdf
                self.assertNotIn('/', entry['Exe'])
                self.assertNotIn('/', entry['StartDir'])

    def test_save_shortcuts_vdf_readonly_file(self):
        import stat
        with tempfile.TemporaryDirectory() as tmpdir:
            vdf_path = os.path.join(tmpdir, "shortcuts.vdf")
            save_shortcuts_vdf(vdf_path, {'shortcuts': {'0': {'AppName': 'BeforeReadOnly'}}})

            # Set file as read-only
            attrs = os.stat(vdf_path).st_mode
            os.chmod(vdf_path, attrs & ~stat.S_IWRITE)

            # Saving updated data must succeed by unsetting read-only
            new_data = {'shortcuts': {'0': {'AppName': 'AfterReadOnly'}}}
            ok = save_shortcuts_vdf(vdf_path, new_data)
            self.assertTrue(ok)

            loaded = load_shortcuts_vdf(vdf_path)
            self.assertEqual(loaded['shortcuts']['0']['AppName'], 'AfterReadOnly')

    def test_is_safe_valve_url_strict_allowlist(self):
        # Valid official Valve endpoints
        valid_urls = [
            "https://store.steampowered.com/api/storesearch/?term=test",
            "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/10/library_600x900.jpg",
            "https://steamcdn-a.akamaihd.net/steam/apps/10/header.jpg",
            "https://cdn.cloudflare.steamstatic.com/steam/apps/10/logo.png",
            "https://store.steampowered.com:443/app/10"
        ]
        for url in valid_urls:
            self.assertTrue(is_safe_valve_url(url), f"Should be allowed: {url}")

        # Invalid: HTTP scheme
        self.assertFalse(is_safe_valve_url("http://store.steampowered.com/api/test"))
        # Invalid: Non-standard port (SSRF port scanning attempt)
        self.assertFalse(is_safe_valve_url("https://store.steampowered.com:8080/test"))
        self.assertFalse(is_safe_valve_url("https://store.steampowered.com:22/test"))
        # Invalid: User info embedded
        self.assertFalse(is_safe_valve_url("https://admin:pass@store.steampowered.com/test"))
        # Invalid: Non-whitelisted domains / IPs
        self.assertFalse(is_safe_valve_url("https://127.0.0.1/test"))
        self.assertFalse(is_safe_valve_url("https://169.254.169.254/latest/meta-data/"))
        self.assertFalse(is_safe_valve_url("https://evil-steam.com/test"))
        self.assertFalse(is_safe_valve_url("https://store.steampowered.com.attacker.com/test"))
        # Invalid: null/empty/non-string
        self.assertFalse(is_safe_valve_url(None))
        self.assertFalse(is_safe_valve_url(""))
        self.assertFalse(is_safe_valve_url("   "))

    def test_is_safe_grid_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            grid_dir = os.path.join(tmpdir, "grid")
            os.makedirs(grid_dir, exist_ok=True)

            # Valid names
            self.assertTrue(is_safe_grid_path(os.path.join(grid_dir, "12345p.png"), grid_dir))
            self.assertTrue(is_safe_grid_path(os.path.join(grid_dir, "12345_hero.png"), grid_dir))
            self.assertTrue(is_safe_grid_path(os.path.join(grid_dir, "12345_logo.png"), grid_dir))
            self.assertTrue(is_safe_grid_path(os.path.join(grid_dir, "12345.png"), grid_dir))
            self.assertTrue(is_safe_grid_path(os.path.join(grid_dir, "-987654p.png"), grid_dir))

            # Path traversal attempts
            self.assertFalse(is_safe_grid_path(os.path.join(grid_dir, "..", "shortcuts.vdf"), grid_dir))
            self.assertFalse(is_safe_grid_path(os.path.join(grid_dir, "..", "..", "evil.png"), grid_dir))

            # Non-standard extensions
            self.assertFalse(is_safe_grid_path(os.path.join(grid_dir, "12345.exe"), grid_dir))
            self.assertFalse(is_safe_grid_path(os.path.join(grid_dir, "12345.bat"), grid_dir))
            self.assertFalse(is_safe_grid_path(os.path.join(grid_dir, "12345.jpg"), grid_dir))

            # Subdirectory inside grid (must reside directly in grid/)
            subdir = os.path.join(grid_dir, "nested")
            os.makedirs(subdir, exist_ok=True)
            self.assertFalse(is_safe_grid_path(os.path.join(subdir, "12345p.png"), grid_dir))

            # Case insensitivity normalization on Windows
            upper_grid = grid_dir.upper()
            lower_target = os.path.join(grid_dir.lower(), "12345p.png")
            self.assertTrue(is_safe_grid_path(lower_target, upper_grid))

    def test_is_safe_steam_user_id(self):
        self.assertTrue(is_safe_steam_user_id("12345678"))
        self.assertTrue(is_safe_steam_user_id(12345678))
        self.assertTrue(is_safe_steam_user_id("0"))

        # Path traversal and injection attempts
        self.assertFalse(is_safe_steam_user_id("../../123456"))
        self.assertFalse(is_safe_steam_user_id("..\\123456"))
        self.assertFalse(is_safe_steam_user_id("1234/56"))
        self.assertFalse(is_safe_steam_user_id("1234;rm"))
        self.assertFalse(is_safe_steam_user_id("admin_user"))
        self.assertFalse(is_safe_steam_user_id(""))
        self.assertFalse(is_safe_steam_user_id("   "))
        self.assertFalse(is_safe_steam_user_id(None))

    def test_safe_requests_get_ssrf_redirect_defense(self):
        # Hop to an untrusted URL must be rejected
        mock_hop = MagicMock()
        mock_hop.url = "http://169.254.169.254/latest/meta-data/"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.history = [mock_hop]
        mock_resp.url = "https://store.steampowered.com/api/test"

        with patch('requests.get', return_value=mock_resp):
            res = safe_requests_get("https://store.steampowered.com/api/test")
            self.assertIsNone(res)

        # Final destination redirecting to untrusted domain must be rejected
        mock_hop2 = MagicMock()
        mock_hop2.url = "https://store.steampowered.com/api/test"
        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.history = [mock_hop2]
        mock_resp2.url = "https://evil-attacker.com/malicious.png"

        with patch('requests.get', return_value=mock_resp2):
            res2 = safe_requests_get("https://store.steampowered.com/api/test")
            self.assertIsNone(res2)

    def test_close_steam_client_uses_cli_and_no_startfile(self):
        with patch('steam_syncer.is_steam_running', side_effect=[True, False]), \
             patch('steam_syncer.get_steam_path', return_value=r"C:\Program Files (x86)\Steam"), \
             patch('os.path.isfile', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('os.startfile') as mock_startfile:
            ok = close_steam_client(timeout_sec=1.0)
            self.assertTrue(ok)
            mock_startfile.assert_not_called()
            self.assertTrue(mock_run.called)
            # Ensure steam -shutdown command line argument was passed
            called_args = mock_run.call_args[0][0]
            self.assertIn("-shutdown", called_args)

    def test_get_available_drives(self):
        drives = get_available_drives()
        self.assertIsInstance(drives, list)
        self.assertGreater(len(drives), 0)

    def test_get_default_game_folders_candidates(self):
        all_candidates = get_default_game_folders(existing_only=False)
        self.assertIsInstance(all_candidates, list)
        self.assertGreater(len(all_candidates), 10)
        # Verify coverage of all requested launchers
        cand_str = " ".join(all_candidates).lower()
        self.assertIn("games", cand_str)
        self.assertIn("epic games", cand_str)
        self.assertIn("gog", cand_str)
        self.assertIn("ea games", cand_str)
        self.assertIn("ubisoft", cand_str)
        self.assertIn("amazon games", cand_str)
        self.assertIn("itch", cand_str)
        self.assertIn("playnite", cand_str)

    def test_launcher_executables_ignored_in_scan(self):
        launcher_exes = [
            "EpicGamesLauncher.exe", "GalaxyClient.exe", "EADesktop.exe",
            "Origin.exe", "UbisoftConnect.exe", "uplay.exe",
            "AmazonGames.exe", "Playnite.DesktopApp.exe", "itch.exe",
            "steam.exe"
        ]
        for le in launcher_exes:
            self.assertFalse(is_valid_executable(le), f"Launcher binary {le} must be ignored")

    def test_launcher_subfolders_ignored_in_scan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a launcher folder structure
            launcher_dir = os.path.join(tmpdir, "Launcher")
            os.makedirs(launcher_dir, exist_ok=True)
            with open(os.path.join(launcher_dir, "EpicGamesLauncher.exe"), "wb") as f:
                f.write(b"\x00" * 1024)

            # Create an actual game folder structure
            game_dir = os.path.join(tmpdir, "MyGame")
            os.makedirs(game_dir, exist_ok=True)
            with open(os.path.join(game_dir, "MyGame.exe"), "wb") as f:
                f.write(b"\x00" * 1024)

            games = scan_games(tmpdir)
            game_names = [g['clean_name'] for g in games]
            self.assertIn("MyGame", game_names)
            self.assertNotIn("Launcher", game_names)


class ArchitectureStagesTests(unittest.TestCase):
    def test_stage1_steam_lifecycle_api(self):
        import steam_lifecycle
        self.assertTrue(callable(steam_lifecycle.get_steam_path))
        self.assertTrue(callable(steam_lifecycle.get_active_steam_user))
        self.assertTrue(callable(steam_lifecycle.is_steam_running))
        self.assertTrue(callable(steam_lifecycle.safe_close_steam))
        self.assertTrue(callable(steam_lifecycle.launch_steam))

    def test_stage2_epic_launcher_strict_exclusion(self):
        import json
        from scanners.discovered_game import DiscoveredGame
        from scanners.epic import scan_epic_games
        from steam_syncer import scan_epic_games_manifests

        # Test DiscoveredGame dual access
        game_obj = DiscoveredGame("Cyberpunk 2077", "C:/Games/Cyberpunk.exe", "C:/Games", "Epic")
        self.assertEqual(game_obj.name, "Cyberpunk 2077")
        self.assertEqual(game_obj['name'], "Cyberpunk 2077")
        self.assertEqual(game_obj.exe_path, os.path.normpath("C:/Games/Cyberpunk.exe"))
        self.assertEqual(game_obj['exe_path'], os.path.normpath("C:/Games/Cyberpunk.exe"))
        self.assertEqual(game_obj.start_dir, os.path.normpath("C:/Games"))
        self.assertEqual(game_obj['start_dir'], os.path.normpath("C:/Games"))
        self.assertEqual(game_obj.source, "Epic")
        self.assertEqual(game_obj['source'], "Epic")

        with tempfile.TemporaryDirectory() as tmp_manifest_dir:
            # Manifest 1: Epic Games Launcher Client (MUST BE IGNORED)
            launcher_install_dir = os.path.join(tmp_manifest_dir, "EpicGames", "Launcher")
            os.makedirs(launcher_install_dir, exist_ok=True)
            launcher_exe = os.path.join(launcher_install_dir, "EpicGamesLauncher.exe")
            with open(launcher_exe, "wb") as f:
                f.write(b"\x00" * 1024)

            launcher_manifest = {
                "AppName": "Launcher",
                "DisplayName": "Epic Games Launcher",
                "InstallLocation": launcher_install_dir,
                "LaunchExecutable": "EpicGamesLauncher.exe"
            }
            with open(os.path.join(tmp_manifest_dir, "Launcher.item"), "w", encoding="utf-8") as f:
                json.dump(launcher_manifest, f)

            # Manifest 2: EOS Bootstrapper / Prerequisites (MUST BE IGNORED)
            eos_manifest = {
                "AppName": "EOSBootstrapper",
                "DisplayName": "Epic Online Services",
                "InstallLocation": launcher_install_dir,
                "LaunchExecutable": "EOSBootStrapper.exe"
            }
            with open(os.path.join(tmp_manifest_dir, "EOS.item"), "w", encoding="utf-8") as f:
                json.dump(eos_manifest, f)

            # Manifest 3: Legitimate Game (Hades) (MUST BE DETECTED)
            game_install_dir = os.path.join(tmp_manifest_dir, "HadesGame")
            os.makedirs(game_install_dir, exist_ok=True)
            game_exe = os.path.join(game_install_dir, "Hades.exe")
            with open(game_exe, "wb") as f:
                f.write(b"\x00" * 1024)

            game_manifest = {
                "AppName": "Minos",
                "DisplayName": "Hades",
                "InstallLocation": game_install_dir,
                "LaunchExecutable": "Hades.exe"
            }
            with open(os.path.join(tmp_manifest_dir, "Hades.item"), "w", encoding="utf-8") as f:
                json.dump(game_manifest, f)

            # Test both scanner implementations
            detected_syncer = scan_epic_games_manifests(tmp_manifest_dir)
            detected_scanner = scan_epic_games(tmp_manifest_dir)

            for result_list in (detected_syncer, detected_scanner):
                names = [g['clean_name'] if isinstance(g, dict) and 'clean_name' in g else g.name for g in result_list]
                self.assertIn("Hades", names)
                self.assertNotIn("Epic Games Launcher", names)
                self.assertNotIn("Launcher", names)
                self.assertNotIn("Epic Online Services", names)
                self.assertEqual(len(result_list), 1)

    def test_stage3_steam_vdf_module(self):
        import steam_vdf
        self.assertTrue(callable(steam_vdf.backup_shortcuts))
        self.assertTrue(callable(steam_vdf.load_shortcuts))
        self.assertTrue(callable(steam_vdf.save_shortcuts))
        self.assertTrue(callable(steam_vdf.calculate_appid))
        self.assertTrue(callable(steam_vdf.generate_shortcut_entry))

        entry = steam_vdf.generate_shortcut_entry({
            'exe_path': r'C:\Games\Doom\Doom.exe',
            'clean_name': 'DOOM',
            'start_dir': r'C:\Games\Doom'
        })
        self.assertIn('appid', entry)
        self.assertIn('AppName', entry)
        self.assertEqual(entry['AppName'], 'DOOM')
        self.assertEqual(entry['Exe'], r'"C:\Games\Doom\Doom.exe"')
        self.assertEqual(entry['StartDir'], r'"C:\Games\Doom"')
        self.assertEqual(entry['AllowDesktopConfig'], 1)
        self.assertEqual(entry['AllowOverlay'], 1)

        # Verify ShortcutEntry case-insensitivity wrapper
        sc_entry = steam_vdf.ShortcutEntry(entry)
        self.assertEqual(sc_entry['appname'], 'DOOM')
        self.assertEqual(sc_entry['AppName'], 'DOOM')
        self.assertEqual(sc_entry['exe'], r'"C:\Games\Doom\Doom.exe"')

    def test_stage4_artwork_scraper_module(self):
        import artwork_scraper
        self.assertTrue(hasattr(artwork_scraper, 'SteamGridDBClient'))
        self.assertTrue(hasattr(artwork_scraper, 'DEFAULT_STEAMGRIDDB_KEY'))
        self.assertTrue(callable(artwork_scraper.download_artwork_for_game))

    def test_stage5_gui_button_state_logic(self):
        import i18n
        from i18n import tr
        from steam_syncer_gui import MainWindow, configure_high_dpi, get_or_create_qapp, ensure_qfluentwidgets_alive
        from PyQt6.QtWidgets import QApplication

        configure_high_dpi()
        app = get_or_create_qapp()
        ensure_qfluentwidgets_alive(app)
        win = MainWindow()
        try:
            # Case 1: Games found, all already in library (new_count == 0, count == 3)
            win._scanned_games_count = 3
            win._current_games = [
                {'clean_name': 'Game1', 'exe_path': 'C:/g1.exe', 'is_registered': True, 'selected': True},
                {'clean_name': 'Game2', 'exe_path': 'C:/g2.exe', 'is_registered': True, 'selected': True},
                {'clean_name': 'Game3', 'exe_path': 'C:/g3.exe', 'is_registered': True, 'selected': True},
            ]
            win.update_sync_button_text()
            self.assertFalse(win.btn_sync.isEnabled())
            self.assertEqual(win.btn_sync.text(), tr("btn_sync_all_up_to_date"))

            # Case 2: Games found, with 2 new games (new_count == 2, count == 3)
            win._current_games = [
                {'clean_name': 'Game1', 'exe_path': 'C:/g1.exe', 'is_registered': False, 'selected': True},
                {'clean_name': 'Game2', 'exe_path': 'C:/g2.exe', 'is_registered': False, 'selected': True},
                {'clean_name': 'Game3', 'exe_path': 'C:/g3.exe', 'is_registered': True, 'selected': True},
            ]
            win.update_sync_button_text()
            self.assertTrue(win.btn_sync.isEnabled())
            self.assertEqual(win.btn_sync.text(), f"{tr('btn_sync')} (2)")

            # Case 3: Empty scan or reset (count == 0)
            win.clear_game_cards()
            self.assertTrue(win.btn_sync.isEnabled())
            self.assertEqual(win.btn_sync.text(), tr("btn_sync"))
        finally:
            win.close()

    def test_red_team_bug_fixes(self):
        from PIL import Image
        import steam_vdf
        import steam_syncer
        import steam_syncer_gui
        import steam_lifecycle

        # 1. ShortcutEntry.__contains__
        entry = steam_vdf.generate_shortcut_entry({
            'exe_path': r'C:\Games\Test\test.exe',
            'clean_name': 'Test Game',
            'tags': ['Action', 'RPG']
        })
        self.assertIn('appname', entry)
        self.assertIn('AppName', entry)
        self.assertIn('exe', entry)
        self.assertIn('Exe', entry)
        self.assertIn('startdir', entry)
        self.assertEqual(entry['tags'], {'0': 'Action', '1': 'RPG'})

        # 2. is_safe_grid_path argument order
        valid_grid_dir = r"C:\Steam\userdata\12345\config\grid"
        valid_dest = r"C:\Steam\userdata\12345\config\grid\12345p.png"
        self.assertTrue(steam_syncer.is_safe_grid_path(valid_dest, valid_grid_dir))
        self.assertFalse(steam_syncer.is_safe_grid_path(valid_grid_dir, valid_dest))

        # 3. copy_or_link_64bit same-file guard
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"artwork_bytes")
            tf_path = tf.name
        try:
            # Should not raise SameFileError
            steam_syncer.copy_or_link_64bit(tf_path, tf_path)
        finally:
            try:
                os.remove(tf_path)
            except OSError:
                pass

        # 4. safe_requests_get non-http scheme rejection
        self.assertIsNone(steam_syncer.safe_requests_get("file:///C:/Windows/System32/cmd.exe"))
        self.assertIsNone(steam_syncer.safe_requests_get("ftp://malicious.host/file.png"))

        # 5. save_app_config atomic write
        with tempfile.TemporaryDirectory() as tmp_cfg_dir:
            orig_cfg = steam_syncer_gui.CONFIG_PATH
            try:
                steam_syncer_gui.CONFIG_PATH = os.path.join(tmp_cfg_dir, "config.json")
                steam_syncer_gui.save_app_config({'test_key': 'atomic_value'})
                loaded = steam_syncer_gui.load_app_config()
                self.assertEqual(loaded.get('test_key'), 'atomic_value')
            finally:
                steam_syncer_gui.CONFIG_PATH = orig_cfg

        # 6. get_cover_accent_color caching
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
            img = Image.new('RGB', (100, 100), color=(120, 60, 200))
            img.save(tf.name)
            img_path = tf.name
        try:
            c1 = steam_syncer_gui.get_cover_accent_color(img_path)
            self.assertIsNotNone(c1)
            self.assertIn(img_path, steam_syncer_gui._ACCENT_COLOR_CACHE)
            c2 = steam_syncer_gui.get_cover_accent_color(img_path)
            self.assertEqual(c1, c2)
        finally:
            try:
                os.remove(img_path)
            except OSError:
                pass

        # 7. is_big_picture_mode_running PID isolation
        with patch('sys.platform', 'win32'), \
             patch('steam_lifecycle.get_running_steam_pids', return_value={1001}), \
             patch('ctypes.windll.user32.FindWindowW', return_value=9999):
            def mock_get_thread_proc_id(hwnd, pid_ptr):
                pid_ptr._obj.value = 2002  # Different PID, not in steam_pids
                return 1
            with patch('ctypes.windll.user32.GetWindowThreadProcessId', side_effect=mock_get_thread_proc_id):
                self.assertFalse(steam_lifecycle.is_big_picture_mode_running())

        # 8. Test DeckBridge paths and MSIX AppData redirection
        self.assertTrue(hasattr(steam_syncer_gui, 'COVERS_CACHE_DIR'))
        self.assertTrue(os.path.isdir(steam_syncer_gui.COVERS_CACHE_DIR))
        self.assertIn('DeckBridge', steam_syncer_gui.COVERS_CACHE_DIR)
        with tempfile.TemporaryDirectory() as empty_base:
            with patch('steam_syncer_gui.BASE_DIR', empty_base):
                clean_cfg = steam_syncer_gui.get_default_config_path()
                self.assertIn('DeckBridge', clean_cfg)
                self.assertTrue(clean_cfg.endswith('config.json'))

            # Portable writable config detected
            portable_cfg_file = os.path.join(empty_base, "config.json")
            with open(portable_cfg_file, 'w') as f:
                f.write('{"portable": true}')
            with patch('steam_syncer_gui.BASE_DIR', empty_base):
                cfg_found = steam_syncer_gui.get_default_config_path()
                self.assertEqual(cfg_found, portable_cfg_file)

            # Read-only container (MSIX WindowsApps simulation) falls back to LocalAppData
            with patch('steam_syncer_gui.BASE_DIR', empty_base), \
                 patch('os.access', return_value=False):
                fallback_cfg = steam_syncer_gui.get_default_config_path()
                self.assertIn('DeckBridge', fallback_cfg)
                self.assertNotIn(empty_base, fallback_cfg)


if __name__ == '__main__':
    unittest.main()
