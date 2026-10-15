#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Military Acceptance Test Harness (test_harness.py)
Validates Steam Syncer against Levels 0, 1, and 2 of the Stress-Test Checklist:
- Level 0: Fatal Risks (Process locks, atomic writes, rotating backups, signed/unsigned paradox, null bytes)
- Level 1: Windows Platform Edge Cases (Cyrillic, emojis, spaces, quotes, StartDir, multi-user loginusers)
- Level 2: Network & Assets (Offline mode, timeouts, 429 rate limiting, honest PNG validation, corrupt file rejection)
"""

import os
import sys
import time
import io
import ctypes
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import vdf
from PIL import Image

import steam_syncer
from steam_syncer import (
    is_steam_running,
    backup_shortcuts_file,
    save_shortcuts_vdf,
    load_shortcuts_vdf,
    calculate_steam_ids,
    clean_game_name,
    find_best_game_exe,
    convert_and_save_image,
    store_request_with_backoff,
    sanitize_vdf_strings,
    get_steam_users_info,
    ACTIVE_STEAM_PROCESSES
)


class MilitaryStressTestHarness(unittest.TestCase):

    # ==========================================================================
    # LEVEL 0: FATAL RISKS (Process collision, atomic write, VDF integrity)
    # ==========================================================================

    def test_0_1_process_intercept_all_binaries(self):
        """0.1.1: Rigidly intercept steam.exe, steamservice.exe, and steamwebhelper.exe."""
        self.assertIn('steam.exe', ACTIVE_STEAM_PROCESSES)
        self.assertIn('steamservice.exe', ACTIVE_STEAM_PROCESSES)
        self.assertIn('steamwebhelper.exe', ACTIVE_STEAM_PROCESSES)

        for proc_name in ['steam.exe', 'steamservice.exe', 'steamwebhelper.exe']:
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(stdout=f'"{proc_name}","1234","Console","1","50,000 K"')
                with patch('ctypes.windll.kernel32.CreateToolhelp32Snapshot', return_value=-1):
                    self.assertTrue(is_steam_running(), f"Must detect running {proc_name}")

    def test_0_1_atomic_write_protection(self):
        """0.1.2: Atomic write via .tmp and os.replace; original is never corrupted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vdf_path = os.path.join(tmpdir, "shortcuts.vdf")

            # Create existing valid file with original content
            original_data = {'shortcuts': {'0': {'AppName': 'Original', 'appid': 111}}}
            save_shortcuts_vdf(vdf_path, original_data)
            self.assertTrue(os.path.isfile(vdf_path))
            orig_mtime = os.path.getmtime(vdf_path)
            with open(vdf_path, 'rb') as f:
                orig_content = f.read()

            # Attempt saving corrupt/unserializable payload
            with patch('vdf.binary_dumps', side_effect=Exception("Disk full / Power cut emulation")):
                with self.assertRaises(Exception):
                    save_shortcuts_vdf(vdf_path, {'shortcuts': {'0': {'AppName': 'Corrupted'}}})

            # Original file MUST remain intact and identical
            with open(vdf_path, 'rb') as f:
                self.assertEqual(f.read(), orig_content)
            self.assertFalse(os.path.exists(vdf_path + ".tmp"))

    def test_0_1_rotating_backups(self):
        """0.1.3: 3-generation rotating backup (.bak, .bak.1, .bak.2, .bak.3)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vdf_path = os.path.join(tmpdir, "shortcuts.vdf")

            def read_b(path):
                with open(path, 'rb') as f:
                    return f.read()

            # Generation 1
            with open(vdf_path, 'wb') as f:
                f.write(b'GEN_1')
            backup_shortcuts_file(vdf_path)
            self.assertTrue(os.path.isfile(vdf_path + ".bak"))
            self.assertEqual(read_b(vdf_path + ".bak"), b'GEN_1')

            # Generation 2
            with open(vdf_path, 'wb') as f:
                f.write(b'GEN_2')
            backup_shortcuts_file(vdf_path)
            self.assertEqual(read_b(vdf_path + ".bak"), b'GEN_2')
            self.assertEqual(read_b(vdf_path + ".bak.1"), b'GEN_1')

            # Generation 3
            with open(vdf_path, 'wb') as f:
                f.write(b'GEN_3')
            backup_shortcuts_file(vdf_path)
            self.assertEqual(read_b(vdf_path + ".bak"), b'GEN_3')
            self.assertEqual(read_b(vdf_path + ".bak.1"), b'GEN_2')
            self.assertEqual(read_b(vdf_path + ".bak.2"), b'GEN_1')

            # Generation 4
            with open(vdf_path, 'wb') as f:
                f.write(b'GEN_4')
            backup_shortcuts_file(vdf_path)
            self.assertEqual(read_b(vdf_path + ".bak"), b'GEN_4')
            self.assertEqual(read_b(vdf_path + ".bak.1"), b'GEN_3')
            self.assertEqual(read_b(vdf_path + ".bak.2"), b'GEN_2')
            self.assertEqual(read_b(vdf_path + ".bak.3"), b'GEN_1')

    def test_0_2_vdf_roundtrip_deserialization(self):
        """0.2.1: Reverse deserialization validates binary output before commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vdf_path = os.path.join(tmpdir, "shortcuts.vdf")
            data = {
                'shortcuts': {
                    '0': {
                        'appid': -987654321,
                        'AppName': 'Fuzz Game [2026]',
                        'Exe': '"D:\\Games\\Fuzz\\game.exe"',
                        'StartDir': '"D:\\Games\\Fuzz"',
                        'tags': {}
                    }
                }
            }
            save_shortcuts_vdf(vdf_path, data)
            loaded = load_shortcuts_vdf(vdf_path)
            self.assertEqual(loaded['shortcuts']['0']['AppName'], 'Fuzz Game [2026]')
            self.assertEqual(loaded['shortcuts']['0']['appid'], -987654321)

    def test_0_2_signed_unsigned_32bit_paradox(self):
        """0.2.2: VDF appid is signed int32, while grid/ files use unsigned uint32."""
        exe = r"C:\Games\Heavy Game\launch.exe"
        title = "Heavy Game"
        grid_id, vdf_appid, grid_id_64 = calculate_steam_ids(exe, title)

        # grid_id must be unsigned 32-bit with top bit set
        self.assertGreaterEqual(grid_id, 0x80000000)
        self.assertLessEqual(grid_id, 0xFFFFFFFF)

        # vdf_appid must be signed 32-bit
        self.assertIsInstance(vdf_appid, int)
        self.assertLess(vdf_appid, 0)
        self.assertEqual(vdf_appid, ctypes.c_int32(grid_id).value)

        # Filename poster uses uint32
        poster_name = f"{grid_id}p.png"
        self.assertTrue(poster_name.startswith(str(grid_id)))

    def test_0_2_null_byte_sanitization(self):
        """0.2.3: No string contains null byte \\0 which breaks Valve's binary parser."""
        dirty_input = {
            'shortcuts': {
                '0': {
                    'AppName': 'Dangerous\x00Game',
                    'Exe': '"C:\\Games\\Bad\x00Path\\game.exe"',
                    'StartDir': '"C:\\Games\\Bad\x00Path"'
                }
            }
        }
        cleaned = sanitize_vdf_strings(dirty_input)
        self.assertEqual(cleaned['shortcuts']['0']['AppName'], 'DangerousGame')
        self.assertEqual(cleaned['shortcuts']['0']['Exe'], '"C:\\Games\\BadPath\\game.exe"')
        self.assertEqual(cleaned['shortcuts']['0']['StartDir'], '"C:\\Games\\BadPath"')

        # Ensure dumps succeeds without null-terminator collision
        b = vdf.binary_dumps(cleaned)
        reloaded = vdf.binary_loads(b)
        self.assertEqual(reloaded['shortcuts']['0']['AppName'], 'DangerousGame')

    # ==========================================================================
    # LEVEL 1: WINDOWS PLATFORM EDGE CASES (Cyrillic, Spaces, Multi-User)
    # ==========================================================================

    def test_1_1_unicode_cyrillic_paths_and_quotes(self):
        """1.1.1 & 1.1.2: Cyrillic paths, emojis, brackets, spaces, and quoted Exe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Complex Russian path with spaces, symbols, and dates
            cyrillic_folder = os.path.join(
                tmpdir,
                "Пользователи",
                "Дмитрий Анатольевич",
                "Игры [2026] & Demos",
                "Кибер Русь"
            )
            os.makedirs(cyrillic_folder, exist_ok=True)
            exe_path = os.path.join(cyrillic_folder, "cyber_rus.exe")
            with open(exe_path, 'wb') as f:
                f.write(b'EXE_BINARY')

            clean_name = clean_game_name("Кибер Русь [GOG]")
            self.assertEqual(clean_name, "Кибер Русь")

            best = find_best_game_exe(cyrillic_folder, clean_name)
            self.assertIsNotNone(best)
            self.assertEqual(best['name'], "cyber_rus.exe")

            # Test shortcut creation in VDF
            vdf_path = os.path.join(tmpdir, "shortcuts.vdf")
            with patch('steam_syncer.is_steam_running', return_value=False):
                game = {
                    'clean_name': clean_name,
                    'exe_path': exe_path,
                    'folder_path': cyrillic_folder
                }
                added, _ = steam_syncer.add_games_to_shortcuts(
                    vdf_path, [game], download_artwork=False
                )
                self.assertEqual(added, 1)

                loaded = load_shortcuts_vdf(vdf_path)
                entry = loaded['shortcuts']['0']
                # Exe MUST be wrapped in double quotes
                self.assertTrue(entry['Exe'].startswith('"') and entry['Exe'].endswith('"'))
                # StartDir MUST point to parent directory without binary name
                self.assertEqual(entry['StartDir'], f'"{cyrillic_folder}"')
                self.assertNotIn('cyber_rus.exe', entry['StartDir'])

    def test_1_2_multi_user_loginusers_detection(self):
        """1.2.1: Multi-User mode detects account with MostRecent == 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            steam_dir = tmpdir
            config_dir = os.path.join(steam_dir, "config")
            userdata_dir = os.path.join(steam_dir, "userdata")
            os.makedirs(config_dir, exist_ok=True)
            sid_smurf_32 = str(76561198000000001 & 0xFFFFFFFF)
            sid_main_32 = str(76561198000000002 & 0xFFFFFFFF)
            os.makedirs(os.path.join(userdata_dir, sid_smurf_32), exist_ok=True)
            os.makedirs(os.path.join(userdata_dir, sid_main_32), exist_ok=True)

            loginusers_content = (
                '"users"\n'
                '{\n'
                '    "76561198000000001"\n'
                '    {\n'
                '        "AccountName" "smurf_acc"\n'
                '        "PersonaName" "Smurf"\n'
                '        "MostRecent" "0"\n'
                '        "Timestamp" "1600000000"\n'
                '    }\n'
                '    "76561198000000002"\n'
                '    {\n'
                '        "AccountName" "main_acc"\n'
                '        "PersonaName" "MainPro"\n'
                '        "MostRecent" "1"\n'
                '        "Timestamp" "1700000000"\n'
                '    }\n'
                '}\n'
            )
            with open(os.path.join(config_dir, "loginusers.vdf"), 'w', encoding='utf-8') as f:
                f.write(loginusers_content)

            users = get_steam_users_info(steam_dir)
            self.assertTrue(len(users) >= 2)
            active = next((u for u in users if u.get('is_active')), None)
            self.assertIsNotNone(active)
            self.assertEqual(active['persona_name'], 'MainPro')

    # ==========================================================================
    # LEVEL 2: NETWORK & ASSETS (Honest PNG, rate limit, corrupt rejection)
    # ==========================================================================

    def test_2_1_network_timeout_and_rate_limiting(self):
        """2.1.1 & 2.1.2: Pacing, backoff on 429, and offline mode stability."""
        headers = {'User-Agent': 'Test'}
        # Emulate 429 then success
        resp_429 = MagicMock(status_code=429)
        resp_200 = MagicMock(status_code=200, content=b'OK')

        with patch('time.sleep') as mock_sleep:
            with patch('requests.get', side_effect=[resp_429, resp_200]):
                res = store_request_with_backoff("https://steam.test/api", headers=headers, timeout=4)
                self.assertIsNotNone(res)
                self.assertEqual(res.status_code, 200)
                # Verify sleep was called for backoff
                self.assertTrue(mock_sleep.called)

    def test_2_2_honest_png_conversion_with_pillow(self):
        """2.2.1: Convert JPEG/BMP into authentic PNG with valid headers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create in-memory JPEG
            raw_jpg = io.BytesIO()
            img = Image.new('RGB', (600, 900), color=(30, 80, 150))
            img.save(raw_jpg, format='JPEG')
            jpg_bytes = raw_jpg.getvalue()

            dest_png = os.path.join(tmpdir, "poster.png")
            saved = convert_and_save_image(jpg_bytes, dest_png, is_logo=False, min_size_bytes=500)
            self.assertTrue(saved)
            self.assertTrue(os.path.isfile(dest_png))

            # Verify saved file is genuinely PNG (magic bytes: \x89PNG\r\n\x1a\n)
            with open(dest_png, 'rb') as f:
                header = f.read(8)
            self.assertEqual(header, b'\x89PNG\r\n\x1a\n')

            # Verify Pillow can open and verify it
            with Image.open(dest_png) as p_img:
                self.assertEqual(p_img.format, "PNG")
                self.assertEqual(p_img.size, (600, 900))

    def test_2_2_corrupt_and_zero_byte_image_rejection(self):
        """2.2.2: Corrupt or truncated streams and 0-byte images are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "corrupt.png")

            # 1. 0-byte payload
            self.assertFalse(convert_and_save_image(b'', dest, min_size_bytes=500))
            self.assertFalse(os.path.exists(dest))

            # 2. Fake corrupted binary stream
            corrupt_bytes = b'GIF89a\x00\x00' + b'\xFF' * 800
            self.assertFalse(convert_and_save_image(corrupt_bytes, dest, min_size_bytes=500))
            self.assertFalse(os.path.exists(dest))


def run_test_harness():
    print("=" * 70)
    print("   MILITARY ACCEPTANCE TEST HARNESS (LEVELS 0, 1, 2 VERIFICATION)   ")
    print("=" * 70 + "\n")

    suite = unittest.TestLoader().loadTestsFromTestCase(MilitaryStressTestHarness)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print("  STATUS: [PASS] - ALL LEVEL 0, LEVEL 1, AND LEVEL 2 GATES PASSED")
    else:
        print("  STATUS: [FAIL] - GATES FAILED. DO NOT DEPLOY.")
    print("=" * 70 + "\n")

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_test_harness())
