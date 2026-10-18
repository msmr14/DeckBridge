#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam Lifecycle Orchestrator (steam_lifecycle.py)
Solves the "Ouroboros Paradox":
Utility launched from Steam library -> User triggers Sync ->
Prepares all assets in memory and temp -> Soft-closes Steam gracefully ->
Atomically updates shortcuts.vdf and artwork -> Resurrects Steam seamlessly.
"""

import os
import sys
import time
import shutil
import ctypes
import logging
import argparse
import tempfile
import subprocess
import stat
from typing import Dict, List, Optional, Tuple, Any

import vdf
from PIL import Image
import re

import steam_syncer

logger = logging.getLogger("SteamLifecycle")

# Process names associated with active Steam client
STEAM_PROCESS_NAMES = {
    'steam.exe',
    'steamwebhelper.exe',
    'steamservice.exe',
    'steam',
    'steamwebhelper'
}

# Win32 Process creation flags for detaching from parent Job Object
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def get_running_steam_processes() -> List[str]:
    """Returns list of running Steam processes."""
    found = []
    if sys.platform != "win32":
        try:
            if os.path.isdir('/proc'):
                for pid in os.listdir('/proc'):
                    if pid.isdigit():
                        try:
                            comm_file = os.path.join('/proc', pid, 'comm')
                            if os.path.isfile(comm_file):
                                with open(comm_file, 'r', encoding='utf-8', errors='ignore') as f:
                                    comm = f.read().strip().lower()
                                    if comm in ('steam', 'steamwebhelper'):
                                        found.append(comm)
                        except (IOError, OSError):
                            continue
        except Exception:
            pass
        if not found:
            try:
                res = subprocess.run(['pgrep', '-x', 'steam'], capture_output=True, text=True, timeout=2, check=False)
                if res.returncode == 0 and res.stdout.strip():
                    found.append('steam')
            except Exception:
                pass
        return found

    try:
        k32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002

        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.Process32First.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.Process32Next.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ('dwSize', ctypes.c_ulong),
                ('cntUsage', ctypes.c_ulong),
                ('th32ProcessID', ctypes.c_ulong),
                ('th32DefaultHeapID', ctypes.c_size_t),
                ('th32ModuleID', ctypes.c_ulong),
                ('cntThreads', ctypes.c_ulong),
                ('th32ParentProcessID', ctypes.c_ulong),
                ('pcPriClassBase', ctypes.c_long),
                ('dwFlags', ctypes.c_ulong),
                ('szExeFile', ctypes.c_char * 260),
            ]

        h = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        invalid_val = ctypes.c_void_p(-1).value
        if h not in (-1, None, 0, invalid_val):
            try:
                pe = PROCESSENTRY32()
                pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
                if k32.Process32First(h, ctypes.byref(pe)):
                    while True:
                        exe_name = pe.szExeFile.decode('utf-8', errors='ignore').lower()
                        if exe_name in STEAM_PROCESS_NAMES:
                            found.append(exe_name)
                        if not k32.Process32Next(h, ctypes.byref(pe)):
                            break
                return found
            finally:
                k32.CloseHandle(h)
    except Exception as e:
        logger.debug(f"Toolhelp snapshot failed: {e}")

    # Fallback to tasklist
    try:
        proc = subprocess.run(
            ['tasklist', '/NH', '/FO', 'CSV'],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            creationflags=CREATE_NO_WINDOW
        )
        for line in proc.stdout.splitlines():
            line_lower = line.lower()
            for sp in STEAM_PROCESS_NAMES:
                if sp in line_lower:
                    found.append(sp)
    except Exception:
        pass

    return found


def is_steam_fully_closed() -> bool:
    """Returns True if none of steam.exe, steamwebhelper.exe, or steam are running."""
    procs = get_running_steam_processes()
    if sys.platform == "win32":
        critical = [p for p in procs if p in ('steam.exe', 'steamwebhelper.exe')]
    else:
        critical = [p for p in procs if p in ('steam', 'steamwebhelper')]
    return len(critical) == 0


def get_running_steam_pids() -> set:
    """Returns set of process IDs for running Steam processes."""
    pids = set()
    if sys.platform != "win32":
        try:
            if os.path.isdir('/proc'):
                for pid in os.listdir('/proc'):
                    if pid.isdigit():
                        try:
                            comm_file = os.path.join('/proc', pid, 'comm')
                            if os.path.isfile(comm_file):
                                with open(comm_file, 'r', encoding='utf-8', errors='ignore') as f:
                                    comm = f.read().strip().lower()
                                    if comm in ('steam', 'steamwebhelper'):
                                        pids.add(int(pid))
                        except (IOError, OSError):
                            continue
        except Exception:
            pass
        if not pids:
            try:
                res = subprocess.run(['pgrep', '-x', 'steam'], capture_output=True, text=True, timeout=2, check=False)
                if res.returncode == 0 and res.stdout:
                    for line in res.stdout.splitlines():
                        if line.strip().isdigit():
                            pids.add(int(line.strip()))
            except Exception:
                pass
        return pids

    try:
        k32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002

        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.Process32First.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.Process32Next.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ('dwSize', ctypes.c_ulong),
                ('cntUsage', ctypes.c_ulong),
                ('th32ProcessID', ctypes.c_ulong),
                ('th32DefaultHeapID', ctypes.c_size_t),
                ('th32ModuleID', ctypes.c_ulong),
                ('cntThreads', ctypes.c_ulong),
                ('th32ParentProcessID', ctypes.c_ulong),
                ('pcPriClassBase', ctypes.c_long),
                ('dwFlags', ctypes.c_ulong),
                ('szExeFile', ctypes.c_char * 260),
            ]

        h = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        invalid_val = ctypes.c_void_p(-1).value
        if h not in (-1, None, 0, invalid_val):
            try:
                pe = PROCESSENTRY32()
                pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
                if k32.Process32First(h, ctypes.byref(pe)):
                    while True:
                        exe_name = pe.szExeFile.decode('utf-8', errors='ignore').lower()
                        if exe_name in STEAM_PROCESS_NAMES:
                            pids.add(pe.th32ProcessID)
                        if not k32.Process32Next(h, ctypes.byref(pe)):
                            break
            finally:
                k32.CloseHandle(h)
    except Exception:
        pass
    return pids


def is_big_picture_mode_running() -> bool:
    """
    Detects whether Steam Big Picture / GamepadUI is currently open.
    On Linux / SteamOS: inspects running Steam process cmdlines for -gamepadui, -tenfoot,
    or checks active gamescope session.
    On Windows: checks top-level Windows for Steam Big Picture window class and confirms PID.
    """
    if sys.platform != "win32":
        # 1. If Steam is not running at all, Big Picture cannot be running
        pids = get_running_steam_pids()
        if not pids:
            return False

        # 2. Inspect /proc/<pid>/cmdline for running Steam processes
        try:
            if os.path.isdir('/proc'):
                for pid in pids:
                    try:
                        cmd_file = os.path.join('/proc', str(pid), 'cmdline')
                        if os.path.isfile(cmd_file):
                            with open(cmd_file, 'rb') as f:
                                cmd = f.read().decode('utf-8', errors='ignore').lower()
                                if '-gamepadui' in cmd or '-tenfoot' in cmd:
                                    return True
                    except (IOError, OSError):
                        continue
        except Exception:
            pass

        # 3. Check if current session is Gamescope (Steam Deck Gaming Mode)
        session_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if "gamescope" in session_desktop or os.environ.get("GAMESCOPE_WAYLAND_DISPLAY"):
            return True

        return False

    try:
        steam_pids = get_running_steam_pids()
        if not steam_pids:
            return False

        user32 = ctypes.windll.user32
        classes = ["CUIEngineWin32", "SPUIWindow", "SDL_app"]
        for cls in classes:
            hwnd = user32.FindWindowW(cls, None)
            if hwnd:
                pid = ctypes.c_ulong(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in steam_pids:
                    return True
    except Exception:
        pass
    return False


def request_steam_shutdown(steam_path: str) -> bool:
    """
    Initiates graceful shutdown of Steam client without force-killing.
    Uses 'steam -shutdown' or graceful taskkill / SIGTERM.
    Eliminates blind os.startfile calls.
    """
    if sys.platform != "win32":
        shutdown_cmds = []
        if steam_path and 'com.valvesoftware.Steam' in steam_path:
            shutdown_cmds.append(["flatpak", "run", "com.valvesoftware.Steam", "-shutdown"])
        if steam_path and os.path.isfile(os.path.join(steam_path, "steam.sh")):
            shutdown_cmds.append([os.path.join(steam_path, "steam.sh"), "-shutdown"])
        if shutil.which("steam"):
            shutdown_cmds.append(["steam", "-shutdown"])
        if shutil.which("flatpak") and ["flatpak", "run", "com.valvesoftware.Steam", "-shutdown"] not in shutdown_cmds:
            shutdown_cmds.append(["flatpak", "run", "com.valvesoftware.Steam", "-shutdown"])

        for cmd in shutdown_cmds:
            try:
                res = subprocess.run(cmd, capture_output=True, timeout=4, check=False)
                if res.returncode == 0:
                    return True
            except Exception:
                continue

        try:
            res = subprocess.run(['pkill', '-TERM', '-x', 'steam'], capture_output=True, timeout=3, check=False)
            return res.returncode == 0
        except Exception:
            return False

    steam_exe = os.path.join(steam_path, "steam.exe")
    if os.path.isfile(steam_exe):
        try:
            subprocess.run(
                [steam_exe, "-shutdown"],
                creationflags=CREATE_NO_WINDOW,
                timeout=4,
                check=False
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to execute steam.exe -shutdown: {e}")

    # Fallback to graceful taskkill (sends WM_CLOSE to top-level windows)
    try:
        subprocess.run(
            ['taskkill', '/IM', 'steam.exe'],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=4,
            check=False
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to trigger graceful taskkill: {e}")
        return False


def wait_for_steam_shutdown(timeout_sec: float = 15.0, poll_interval: float = 0.3) -> bool:
    """
    Wait-polling loop checking for complete termination of Steam processes.
    Polls every 300 ms until timeout_sec is exceeded.
    """
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        if is_steam_fully_closed():
            logger.info(f"Steam gracefully stopped in {time.time() - start_time:.2f}s")
            return True
        time.sleep(poll_interval)
    logger.warning("Steam shutdown wait timed out!")
    return False


def resurrect_steam(steam_path: str, big_picture: bool = False) -> bool:
    """
    Relaunches the Steam client detached from current process tree.
    Supports Linux native Steam, Flatpak Steam, and Windows Job Object breakaway.
    If big_picture is True, launches with -gamepadui (modern Big Picture Mode).
    """
    if sys.platform != "win32":
        args = []
        if steam_path and 'com.valvesoftware.Steam' in steam_path:
            args = ['flatpak', 'run', 'com.valvesoftware.Steam']
        elif steam_path and os.path.isfile(os.path.join(steam_path, 'steam.sh')):
            args = [os.path.join(steam_path, 'steam.sh')]
        elif shutil.which('steam'):
            args = ['steam']
        elif steam_path and os.path.isfile(os.path.join(steam_path, 'steam')):
            args = [os.path.join(steam_path, 'steam')]
        else:
            args = ['steam']

        if big_picture:
            args.append('-gamepadui')

        try:
            subprocess.Popen(args, start_new_session=True)
            logger.info(f"Successfully resurrected Steam on Linux (Big Picture: {big_picture})")
            return True
        except Exception as e:
            logger.error(f"Failed to resurrect Steam on Linux: {e}")
            return False

    steam_exe = os.path.join(steam_path, "steam.exe")
    if not os.path.isfile(steam_exe):
        logger.error(f"Cannot resurrect Steam: {steam_exe} not found")
        return False

    args = [steam_exe]
    if big_picture:
        args.append("-gamepadui")

    creation_flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    if sys.platform == "win32":
        try:
            subprocess.Popen(
                args,
                creationflags=creation_flags | CREATE_BREAKAWAY_FROM_JOB
            )
            logger.info(f"Successfully resurrected Steam with job breakaway (Big Picture: {big_picture})")
            return True
        except OSError:
            pass

    try:
        subprocess.Popen(
            args,
            creationflags=creation_flags
        )
        logger.info(f"Successfully resurrected Steam (Big Picture: {big_picture})")
        return True
    except Exception as e:
        logger.error(f"Failed to resurrect Steam: {e}")
        return False


def is_steam_running() -> bool:
    """Returns True if any critical Steam process is currently active."""
    return not is_steam_fully_closed()


def get_steam_path() -> Optional[str]:
    """Finds Steam installation directory via Windows registry or default locations."""
    return steam_syncer.get_steam_path()


def get_active_steam_user(steam_path: Optional[str] = None) -> Optional[str]:
    """Finds active user ID (SteamID3) in <SteamPath>/userdata/ from loginusers.vdf."""
    sp = steam_path or get_steam_path()
    if not sp:
        return None
    return steam_syncer.get_active_steam_user(sp)


def safe_close_steam(steam_path: Optional[str] = None, timeout_sec: float = 5.0) -> bool:
    """
    Safely and cleanly shuts down the Steam client:
    1. Executes official 'steam -shutdown'.
    2. Waits up to timeout_sec (default 5 seconds) for graceful termination.
    3. If Steam processes do not exit within timeout, performs forced kill fallback.
    Returns True if Steam processes were cleanly terminated, False otherwise.
    """
    if is_steam_fully_closed():
        return True

    sp = steam_path or get_steam_path()
    if sp:
        request_steam_shutdown(sp)

    if wait_for_steam_shutdown(timeout_sec=timeout_sec, poll_interval=0.25):
        return True

    logger.warning("Steam graceful shutdown timed out; executing forced termination fallback...")
    if sys.platform != "win32":
        try:
            subprocess.run(['pkill', '-9', '-x', 'steam'], capture_output=True, timeout=2, check=False)
            subprocess.run(['pkill', '-9', '-x', 'steamwebhelper'], capture_output=True, timeout=2, check=False)
            time.sleep(0.3)
        except Exception as e:
            logger.debug(f"Forced Linux termination error: {e}")
        return is_steam_fully_closed()

    try:
        for proc in STEAM_PROCESS_NAMES:
            subprocess.run(
                ['taskkill', '/F', '/T', '/IM', proc],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=3,
                check=False
            )
        time.sleep(0.3)
    except Exception as e:
        logger.debug(f"Forced termination error: {e}")

    return is_steam_fully_closed()


def launch_steam(steam_path: Optional[str] = None, big_picture: bool = False) -> bool:
    """Launches or resurrects the Steam client detached from current process."""
    sp = steam_path or get_steam_path()
    if not sp:
        return False
    return resurrect_steam(sp, big_picture=big_picture)


# ==============================================================================
# Staging & Atomic Injection Pipeline
# ==============================================================================

class StagedSyncSession:
    """
    Manages the 2-phase lifecycle synchronization:
    Phase 1: Heavy lifting in memory and temp while Steam is still running.
    Phase 2: Fast atomic injection (< 500ms) after graceful Steam shutdown.
    """

    def __init__(
        self,
        game_folders: List[str],
        steam_path: str,
        user_id: str,
        download_artwork: bool = True,
        steamgriddb_key: Optional[str] = None,
        selected_games: Optional[List[Dict[str, Any]]] = None
    ):
        if not steam_syncer.is_safe_steam_user_id(user_id):
            raise ValueError(f"Unsafe or invalid steam user_id format: '{user_id}'")
        self.game_folders = game_folders
        self.steam_path = steam_path
        self.user_id = str(user_id)
        self.download_artwork = download_artwork
        self.steamgriddb_key = steamgriddb_key
        self.selected_games = selected_games

        self.temp_dir = tempfile.mkdtemp(prefix="steam_syncer_staged_")
        self.staged_grid_dir = os.path.join(self.temp_dir, "staged_grid")
        os.makedirs(self.staged_grid_dir, exist_ok=True)

        self.discovered_games: List[Dict[str, Any]] = []
        self.target_shortcuts_data: Dict[str, Any] = {}
        self.staged_art_count: int = 0
        self.was_big_picture: bool = False

    def cleanup(self):
        """Removes temporary staging directory."""
        try:
            if os.path.isdir(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def prepare_stage(self, log_callback=None) -> Dict[str, Any]:
        """
        Stage 1: Heavy network and scanning operations while Steam is alive.
        Does NOT touch Steam/userdata/... at all!
        """
        def log(msg: str):
            logger.info(msg)
            if log_callback:
                log_callback(msg)

        log("Этап 1: Сканирование игр и подготовка во временном хранилище...")
        self.was_big_picture = is_big_picture_mode_running()

        if self.selected_games is not None:
            self.discovered_games = list(self.selected_games)
        else:
            self.discovered_games = steam_syncer.scan_games(self.game_folders)
        if not self.discovered_games:
            return {
                'success': True,
                'message': "Игры не обнаружены в указанных папках.",
                'games_count': 0,
                'art_count': 0
            }

        log(f"Найдено игр для синхронизации: {len(self.discovered_games)}")

        # Load existing shortcuts to merge into memory
        shortcuts_real_path = os.path.join(
            self.steam_path, "userdata", self.user_id, "config", "shortcuts.vdf"
        )
        self.target_shortcuts_data = steam_syncer.load_shortcuts_vdf(shortcuts_real_path)
        if 'shortcuts' not in self.target_shortcuts_data or not isinstance(self.target_shortcuts_data['shortcuts'], dict):
            self.target_shortcuts_data['shortcuts'] = {}

        shortcuts_dict = self.target_shortcuts_data['shortcuts']

        existing_exes = set()
        for _, item in shortcuts_dict.items():
            if isinstance(item, dict):
                exe_val = item.get('Exe', '')
                if isinstance(exe_val, str):
                    existing_exes.add(os.path.normpath(exe_val.strip().strip('"\'')).lower())

        existing_keys = [int(k) for k in shortcuts_dict.keys() if str(k).isdigit()]
        next_index = max(existing_keys) + 1 if existing_keys else 0

        added_games = 0
        real_grid_dir = os.path.join(
            self.steam_path, "userdata", self.user_id, "config", "grid"
        )

        for game in self.discovered_games:
            exe_path = game['exe_path']
            clean_exe_path = os.path.normpath(exe_path.replace('\0', '').strip().strip('"\''))
            norm_exe = clean_exe_path.lower()
            clean_name = game['clean_name']
            grid_id, vdf_appid, grid_id_64 = steam_syncer.calculate_steam_ids(exe_path, clean_name)

            game['grid_id'] = grid_id
            game['vdf_appid'] = vdf_appid
            game['grid_id_64'] = grid_id_64

            already_exists = norm_exe in existing_exes

            if not already_exists:
                if sys.platform != 'win32' and os.path.isfile(clean_exe_path):
                    try:
                        st = os.stat(clean_exe_path)
                        if not (st.st_mode & stat.S_IXUSR):
                            os.chmod(clean_exe_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                    except Exception:
                        pass
                clean_app_name = clean_name.replace('\0', '').strip()
                start_dir_raw = game.get('start_dir') or os.path.dirname(clean_exe_path)
                clean_start_dir = os.path.normpath(start_dir_raw.replace('\0', '').strip().strip('"\''))
                entry = {
                    'appid': vdf_appid,
                    'AppName': clean_app_name,
                    'Exe': f'"{clean_exe_path}"',
                    'StartDir': f'"{clean_start_dir}"',
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
                shortcuts_dict[str(next_index)] = entry
                existing_exes.add(norm_exe)
                next_index += 1
                added_games += 1

            # Download and stage artwork
            if self.download_artwork:
                # Check if real poster exists
                real_poster = os.path.join(real_grid_dir, f"{grid_id}p.png")
                if os.path.isfile(real_poster) and os.path.getsize(real_poster) == 0:
                    try:
                        os.remove(real_poster)
                    except OSError:
                        pass
                needs_art = bool(game.get('custom_cover_path')) or not already_exists or not (os.path.isfile(real_poster) and os.path.getsize(real_poster) > 0)

                if needs_art:
                    log(f"Загрузка обложек из CDN Valve для «{clean_name}»...")
                    steam_appid = steam_syncer.search_steam_store_appid(clean_name)
                    art_count = steam_syncer.download_artwork_for_game(
                        steam_appid=steam_appid,
                        grid_id=grid_id,
                        grid_dir=self.staged_grid_dir,
                        game_folder=game.get('folder_path', ''),
                        grid_id_64=grid_id_64,
                        steamgriddb_key=self.steamgriddb_key,
                        clean_name=clean_name,
                        custom_poster_path=game.get('custom_cover_path')
                    )
                    self.staged_art_count += art_count

        return {
            'success': True,
            'message': "Подготовка завершена.",
            'games_count': added_games,
            'art_count': self.staged_art_count
        }

    def commit_stage(self, log_callback=None) -> bool:
        """
        Stage 3: Fast atomic injection (< 500ms).
        Executed strictly while Steam is NOT running!
        """
        def log(msg: str):
            logger.info(msg)
            if log_callback:
                log_callback(msg)

        if not is_steam_fully_closed():
            log("Ошибка: Steam все еще запущен! Атомарная запись отменена.")
            return False

        t0 = time.time()
        real_grid_dir = os.path.join(
            self.steam_path, "userdata", self.user_id, "config", "grid"
        )
        os.makedirs(real_grid_dir, exist_ok=True)

        # 1. Move staged artwork files with strict path safety & filename validation
        if os.path.isdir(self.staged_grid_dir):
            for f in os.listdir(self.staged_grid_dir):
                if not re.match(r'^-?\d+(_hero|_logo|_icon|-icon|p)?\.png$', f, re.IGNORECASE):
                    log(f"Skipping non-standard artwork file: {f}")
                    continue
                src = os.path.join(self.staged_grid_dir, f)
                dst = os.path.join(real_grid_dir, f)
                if not steam_syncer.is_safe_grid_path(dst, real_grid_dir):
                    log(f"Path traversal detected and blocked: {dst}")
                    continue
                if os.path.isfile(src) and os.path.getsize(src) > 0:
                    if os.path.exists(dst):
                        try:
                            attrs = os.stat(dst).st_mode
                            if not (attrs & stat.S_IWRITE):
                                os.chmod(dst, attrs | stat.S_IWRITE)
                        except Exception:
                            pass
                    try:
                        shutil.copy2(src, dst)
                    except Exception as e:
                        logger.warning(f"Failed to copy artwork {f}: {e}")

        # 2. Atomic shortcuts.vdf write
        shortcuts_real_path = os.path.join(
            self.steam_path, "userdata", self.user_id, "config", "shortcuts.vdf"
        )
        steam_syncer.backup_shortcuts_file(shortcuts_real_path)

        success = steam_syncer.save_shortcuts_vdf(
            shortcuts_real_path, self.target_shortcuts_data
        )

        elapsed_ms = (time.time() - t0) * 1000.0
        log(f"Атомарная запись завершена успешно за {elapsed_ms:.1f} мс!")
        return success


# ==============================================================================
# Full Orchestration Function
# ==============================================================================

def orchestrate_sync_cycle(
    game_folders: List[str],
    steam_path: str,
    user_id: str,
    download_artwork: bool = True,
    restart_steam: bool = True,
    log_callback=None,
    steamgriddb_key: Optional[str] = None,
    selected_games: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Executes the complete Steam Lifecycle Orchestration:
    1. If Steam is running -> Stages everything in memory & temp first.
    2. Gracefully shuts down Steam (-shutdown).
    3. Atomically commits files (< 500ms).
    4. Resurrects Steam (-gamepadui if was in Big Picture, otherwise standard).
    5. If Steam was NOT running -> Direct commit without restarts.
    """
    def log(msg: str):
        logger.info(msg)
        if log_callback:
            log_callback(msg)

    session = StagedSyncSession(
        game_folders=game_folders,
        steam_path=steam_path,
        user_id=user_id,
        download_artwork=download_artwork,
        steamgriddb_key=steamgriddb_key,
        selected_games=selected_games
    )

    try:
        steam_was_running = not is_steam_fully_closed()

        # Phase 1: Heavy work in memory & temp
        prep_result = session.prepare_stage(log_callback=log)
        if not prep_result['success']:
            return prep_result

        # Phase 2: Shutdown if Steam is running
        if steam_was_running:
            log("Запрос мягкого закрытия клиента Steam (-shutdown)...")
            request_steam_shutdown(steam_path)

            log("Ожидание завершения процессов Steam...")
            if not wait_for_steam_shutdown(timeout_sec=15.0):
                log("Предупреждение: Steam не закрылся вовремя. Операция прервана ради безопасности.")
                return {
                    'success': False,
                    'message': "Не удалось безопасно закрыть Steam. Синхронизация отменена.",
                    'games_count': 0,
                    'art_count': 0
                }

        # Phase 3: Fast Atomic Injection
        committed = session.commit_stage(log_callback=log)
        if not committed:
            return {
                'success': False,
                'message': "Ошибка атомарной записи shortcuts.vdf.",
                'games_count': 0,
                'art_count': 0
            }

        # Phase 4: Resurrection
        if steam_was_running and restart_steam:
            log("Воскрешение Steam с обновленной библиотекой...")
            resurrect_steam(steam_path, big_picture=session.was_big_picture)

        return {
            'success': True,
            'message': f"Синхронизация успешно выполнена! Добавлено игр: {prep_result['games_count']}, загружено артов: {prep_result['art_count']}.",
            'games_count': prep_result['games_count'],
            'art_count': prep_result['art_count'],
            'was_restarted': steam_was_running
        }

    finally:
        session.cleanup()


# ==============================================================================
# Detached Worker Launcher (Bypassing Windows Job Object)
# ==============================================================================

def spawn_detached_worker(cmd_args: List[str]) -> bool:
    """
    Launches a command completely detached from the current process tree
    and Windows Job Object using Win32 creation flags (no PowerShell command string injection).
    """
    if not cmd_args or not isinstance(cmd_args, list):
        return False
    if sys.platform == "win32":
        try:
            subprocess.Popen(
                cmd_args,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB,
                shell=False
            )
            return True
        except OSError:
            try:
                subprocess.Popen(
                    cmd_args,
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                    shell=False
                )
                return True
            except Exception as e:
                logger.warning(f"Win32 detached worker fallback failed: {e}")
        except Exception as e:
            logger.warning(f"Win32 breakaway failed: {e}")
    else:
        try:
            subprocess.Popen(cmd_args, start_new_session=True)
            return True
        except Exception as e:
            logger.warning(f"Worker launch failed: {e}")

    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Steam Lifecycle Orchestrator")
    parser.add_argument('--folders', nargs='*', default=[r"D:\Gamess", r"C:\Games"])
    parser.add_argument('--steam-path', default=steam_syncer.get_steam_path())
    parser.add_argument('--user-id')
    parser.add_argument('--no-art', action='store_true')
    parser.add_argument('--no-restart', action='store_true')

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    sp = args.steam_path or steam_syncer.get_steam_path()
    uid = args.user_id or (steam_syncer.get_active_steam_user(sp) if sp else None)

    if not sp or not uid:
        print("Error: Could not locate Steam directory or active user ID.")
        sys.exit(1)

    result = orchestrate_sync_cycle(
        game_folders=args.folders,
        steam_path=sp,
        user_id=uid,
        download_artwork=not args.no_art,
        restart_steam=not args.no_restart
    )

    print("\nResult:", result['message'])
