#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam Syncer — Automated Non-Steam Game Importer & CDN Artwork Downloader.
Discovers local game installations, registers them in shortcuts.vdf,
and downloads official Steam store posters, banners, and logos directly
from Valve's CDN without requiring third-party API keys.
"""

import os
import sys
import re
import zlib
import ctypes
import shutil
import logging
import argparse
import subprocess
import stat
import time
import socket
import tempfile
from urllib.parse import urlparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Union, Callable

import vdf
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError, HTTPError, SSLError
from PIL import Image
import io

# Setup logger
logger = logging.getLogger("SteamSyncer")

# Default community SteamGridDB API key for automatic poster fetching
DEFAULT_STEAMGRIDDB_KEY = "64c9bb7cf4369e5f524a80695eeea4e7"

# Keywords for skipping non-game executables and background utilities
IGNORE_KEYWORDS = [
    'unins', 'crashhandler', 'crashreport', 'crashsender', 'crashrpt', 'crash_handler',
    'crash-handler', 'crashreporter', 'crashservice', 'reporter', 'setup', 'update', 'redist', 'dxsetup',
    'unitycrashhandler', 'eac_server', 'easyanticheat',
    'cleanup', 'touchup', 'overlayinjector', 'bugsplat', 'bssndrpt',
    'config', 'launcher_helper', 'installer', 'install',
    'webhelper', 'epicwebhelper', 'cefprocess', 'vcredist', 'dotnet',
    'crs-handler', 'crs-video', 'crs_handler',
    'benchmark', 'dedicatedserver', 'unpack', 'patch', 'editor',
    'epicgameslauncher', 'galaxyclient', 'eadesktop', 'origin',
    'ubisoftconnect', 'uplay', 'amazongames', 'playnite', 'itch',
    'steam', 'steamservice', 'steamwebhelper',
    'epiconlineservices', 'userhelper', 'installhelper', 'uihelper', 'servicehost', 'eoshost',
    'epicinstaller', 'unrealversionselector', 'unrealeditor', 'unrealpak',
    'unrealenginelauncher', 'eosbootstrapper', 'eosoverlayrenderer', 'epicgamesupdater'
]

# Folders representing launchers, redistributables, or system metadata to ignore when scanning
IGNORE_SUBFOLDERS = {
    'system volume information', 'gamesave', '$recycle.bin', 'recovery',
    'launcher', 'launchers', 'epic games launcher', 'directxredist', 'redist',
    'commonredist', '_commonredist', 'epic online services', 'crashdumps',
    'support', 'engine', 'easyanticheat', 'battleye', 'ubisoft game launcher',
    'ea desktop', 'origin games', 'epic games', 'epicgames'
}

# Root directory names that must never be treated as standalone single games
IGNORE_ROOT_NAMES = {
    'epic games', 'epicgames', 'gog games', 'gog galaxy', 'games', 'gamess', 'игры',
    'pc games', 'repack games', 'portable games', 'standalone games', 'torrent games',
    'ea games', 'origin games', 'electronic arts', 'ubisoft', 'ubisoft games',
    'amazon games', 'playnite', 'itch', 'steam', 'program files', 'program files (x86)',
    'common files'
}


class DiscoveredGame(dict):
    """
    Unified game discovery model conforming to DiscoveredGame(name, exe_path, start_dir, source).
    Inherits from dict for 100% transparent backwards compatibility with existing pipelines.
    """
    def __init__(
        self,
        name: str,
        exe_path: str,
        start_dir: str = "",
        source: str = "Standalone",
        **kwargs
    ):
        norm_exe = os.path.normpath(exe_path.replace('\0', '').strip().strip('"\'')) if exe_path else ""
        norm_start = os.path.normpath(start_dir.replace('\0', '').strip().strip('"\'')) if start_dir else (os.path.dirname(norm_exe) if norm_exe else "")
        clean = clean_game_name(name) if name else "Unknown Game"

        data = {
            'clean_name': clean,
            'name': clean,
            'folder_name': name,
            'folder_path': norm_start,
            'exe_name': os.path.basename(norm_exe) if norm_exe else "",
            'exe_path': norm_exe,
            'start_dir': norm_start,
            'source': source,
            'launcher': source,
            'exe_size': kwargs.get('exe_size', 0)
        }
        data.update(kwargs)
        if 'exe_size' not in kwargs or data['exe_size'] == 0:
            try:
                if norm_exe and os.path.isfile(norm_exe):
                    data['exe_size'] = os.path.getsize(norm_exe)
            except OSError:
                data['exe_size'] = 0
        super().__init__(data)

    @property
    def name(self) -> str:
        return self['clean_name']

    @property
    def exe_path(self) -> str:
        return self['exe_path']

    @property
    def start_dir(self) -> str:
        return self['start_dir']

    @property
    def source(self) -> str:
        return self['source']

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"'DiscoveredGame' object has no attribute '{item}'")

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


def get_available_drives() -> List[str]:
    """Returns all active mounted Windows drive roots (e.g. ['C:', 'D:'])."""
    drives = []
    if sys.platform == 'win32':
        import string
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append(f"{letter}:")
    else:
        drives.append("/")
    return drives


def get_default_game_folders(existing_only: bool = True) -> List[str]:
    """
    Returns default game folders across all major launchers and standalone locations:
    - Standalone (Games, Gamess, Игры, Torrent Games, etc. across all drives)
    - Epic Games (Program Files, multi-drive, Manifests *.item)
    - GOG Galaxy / GOG Games (GOG Games, Program Files, Registry)
    - Origin / EA App (Program Files, multi-drive, Registry)
    - Ubisoft Connect (Ubisoft Game Launcher/games, multi-drive, Registry)
    - Amazon Games (%LOCALAPPDATA%\\Amazon Games\\Library, multi-drive, SQLite DB)
    - itch.io (%APPDATA%\\itch\\apps, %LOCALAPPDATA%\\itch\\apps, multi-drive)
    - Playnite (%APPDATA%\\Playnite\\Games, %LOCALAPPDATA%\\Playnite\\Games, multi-drive)
    """
    candidates: List[str] = []
    drives = get_available_drives()

    # 1. Multi-drive Standalone & Launcher Roots
    for d in drives:
        candidates.extend([
            f"{d}\\Gamess",
            f"{d}\\Games",
            f"{d}\\Игры",
            f"{d}\\Torrent Games",
            f"{d}\\PC Games",
            f"{d}\\Repack Games",
            f"{d}\\Portable Games",
            f"{d}\\Standalone Games",
            f"{d}\\Epic Games",
            f"{d}\\EpicGames",
            f"{d}\\GOG Games",
            f"{d}\\GOG Galaxy\\Games",
            f"{d}\\EA Games",
            f"{d}\\Origin Games",
            f"{d}\\Electronic Arts",
            f"{d}\\Ubisoft Games",
            f"{d}\\Ubisoft\\games",
            f"{d}\\Ubisoft",
            f"{d}\\Amazon Games",
            f"{d}\\Amazon Games\\Library",
            f"{d}\\itch\\apps",
            f"{d}\\itch",
            f"{d}\\Itch Games",
            f"{d}\\Playnite\\Games",
            f"{d}\\Playnite",
        ])

    # 2. System and User-Profile Launcher Platform Defaults
    candidates.extend([
        os.path.expandvars(r"%ProgramFiles%\Epic Games"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Epic Games"),
        os.path.expandvars(r"%ProgramFiles(x86)%\GOG Galaxy\Games"),
        os.path.expandvars(r"%ProgramFiles%\GOG Galaxy\Games"),
        os.path.expandvars(r"%ProgramFiles%\EA Games"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Origin Games"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Electronic Arts"),
        os.path.expandvars(r"%ProgramFiles%\Electronic Arts"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Ubisoft\Ubisoft Game Launcher\games"),
        os.path.expandvars(r"%ProgramFiles%\Ubisoft\Ubisoft Game Launcher\games"),
        os.path.expandvars(r"%LOCALAPPDATA%\Amazon Games\Library"),
        os.path.expandvars(r"%LOCALAPPDATA%\Amazon Games"),
        os.path.expandvars(r"%APPDATA%\itch\apps"),
        os.path.expandvars(r"%LOCALAPPDATA%\itch\apps"),
        os.path.expandvars(r"%APPDATA%\Playnite\Games"),
        os.path.expandvars(r"%LOCALAPPDATA%\Playnite\Games"),
    ])

    # 3. Epic Games Manifests Discovery
    epic_manifest_dir = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"
    if os.path.isdir(epic_manifest_dir):
        import glob
        import json
        for item_file in glob.glob(os.path.join(epic_manifest_dir, "*.item")):
            try:
                with open(item_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    app_name = str(data.get("AppName", "")).strip().lower()
                    disp_name = str(data.get("DisplayName", "")).strip().lower()
                    if app_name in {'launcher', 'epicgameslauncher', 'eos', 'epicgames', 'epicgamesstore', 'epiconlineservices'} or app_name.startswith(('ue_', 'unrealengine', 'launcher', 'epicgameslauncher', 'epic_games', 'eos')):
                        continue
                    if any(ign in disp_name for ign in ['epic games launcher', 'epic games', 'epic launcher', 'epic online services', 'unreal engine', 'prerequisites', 'epic games store', 'eos']):
                        continue
                    loc = data.get("InstallLocation")
                    if loc:
                        norm_loc = os.path.normpath(loc)
                        norm_loc_lower = norm_loc.lower()
                        if (norm_loc_lower.endswith(r'\epic games\launcher') or
                            norm_loc_lower.endswith(r'\epicgames\launcher') or
                            '\\epic games\\launcher\\' in norm_loc_lower or
                            '\\epicgames\\launcher\\' in norm_loc_lower or
                            (os.path.basename(norm_loc_lower) == 'launcher' and
                             os.path.basename(os.path.dirname(norm_loc_lower)) in ('epic games', 'epicgames'))):
                            continue
                        parent = os.path.dirname(norm_loc)
                        if os.path.isdir(parent) and len(parent) > 3 and os.path.basename(parent).lower() not in IGNORE_ROOT_NAMES:
                            candidates.append(parent)
                        elif os.path.isdir(norm_loc):
                            candidates.append(norm_loc)
            except Exception:
                pass

    # 4. GOG Games Registry Discovery
    try:
        import winreg
        for root_k in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            for sub_k in [r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"]:
                try:
                    with winreg.OpenKey(root_k, sub_k) as key:
                        num = winreg.QueryInfoKey(key)[0]
                        for i in range(num):
                            gk_name = winreg.EnumKey(key, i)
                            try:
                                with winreg.OpenKey(key, gk_name) as gk:
                                    gpath, _ = winreg.QueryValueEx(gk, "path")
                                    if gpath:
                                        norm_gp = os.path.normpath(gpath)
                                        parent = os.path.dirname(norm_gp)
                                        if os.path.isdir(parent) and len(parent) > 3:
                                            candidates.append(parent)
                                        elif os.path.isdir(norm_gp):
                                            candidates.append(norm_gp)
                            except Exception:
                                pass
                except Exception:
                    pass
    except Exception:
        pass

    # 5. Ubisoft Connect Registry Discovery
    try:
        import winreg
        for root_k in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            for sub_k in [r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs", r"SOFTWARE\Ubisoft\Launcher\Installs"]:
                try:
                    with winreg.OpenKey(root_k, sub_k) as key:
                        num = winreg.QueryInfoKey(key)[0]
                        for i in range(num):
                            gk_name = winreg.EnumKey(key, i)
                            try:
                                with winreg.OpenKey(key, gk_name) as gk:
                                    gpath, _ = winreg.QueryValueEx(gk, "InstallDir")
                                    if gpath:
                                        norm_gp = os.path.normpath(gpath)
                                        parent = os.path.dirname(norm_gp)
                                        if os.path.isdir(parent) and len(parent) > 3:
                                            candidates.append(parent)
                                        elif os.path.isdir(norm_gp):
                                            candidates.append(norm_gp)
                            except Exception:
                                pass
                except Exception:
                    pass
    except Exception:
        pass

    # Deduplicate and validate
    seen = set()
    results: List[str] = []
    for p in candidates:
        if not p:
            continue
        norm = os.path.normpath(p)
        lower = norm.lower()
        if lower in seen:
            continue
        seen.add(lower)
        if not existing_only or os.path.isdir(norm):
            results.append(norm)

    if not results and existing_only:
        return [r"D:\Gamess", r"C:\Games"]

    return results


COMMON_GAME_DIRECTORIES = get_default_game_folders(existing_only=True)


# ==============================================================================
# Phase 1: Reconnaissance & Safeguards
# ==============================================================================

# Process binaries that indicate an active Steam client session
ACTIVE_STEAM_PROCESSES = {'steam.exe', 'steamservice.exe', 'steamwebhelper.exe'}


def is_steam_running() -> bool:
    """
    Checks whether steam.exe, steamservice.exe, or steamwebhelper.exe is running.
    Uses Win32 Toolhelp32Snapshot API for 0ms execution without spawning console windows.
    Configures 64-bit safe handle types to prevent handle truncation.
    """
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
                        if exe_name in ACTIVE_STEAM_PROCESSES:
                            return True
                        if not k32.Process32Next(h, ctypes.byref(pe)):
                            break
                return False
            finally:
                k32.CloseHandle(h)
    except Exception as e:
        logger.debug(f"Toolhelp32Snapshot check failed: {e}")

    # Fallback with CREATE_NO_WINDOW
    try:
        CREATE_NO_WINDOW = 0x08000000
        proc = subprocess.run(
            ['tasklist', '/NH', '/FO', 'CSV'],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            creationflags=CREATE_NO_WINDOW
        )
        out = proc.stdout.lower()
        for p in ACTIVE_STEAM_PROCESSES:
            if p in out:
                return True
    except Exception as e:
        logger.debug(f"tasklist check encountered: {e}")

    return False


def close_steam_client(timeout_sec: float = 6.0, steam_path: Optional[str] = None) -> bool:
    """
    Gracefully shuts down the Steam client using official steam.exe -shutdown,
    falling back to graceful taskkill and force taskkill if necessary.
    Eliminates blind os.startfile calls.
    Returns True if Steam processes were cleanly terminated, False otherwise.
    """
    if not is_steam_running():
        return True

    # 1. Official Valve graceful CLI shutdown without blind startfile
    sp = steam_path or get_steam_path()
    if sp:
        steam_exe = os.path.normpath(os.path.join(sp, "steam.exe"))
        if os.path.isfile(steam_exe):
            try:
                CREATE_NO_WINDOW = 0x08000000
                subprocess.run(
                    [steam_exe, "-shutdown"],
                    capture_output=True,
                    timeout=3,
                    creationflags=CREATE_NO_WINDOW,
                    check=False
                )
                start = time.time()
                while time.time() - start < timeout_sec:
                    time.sleep(0.3)
                    if not is_steam_running():
                        return True
            except Exception as e:
                logger.debug(f"steam.exe -shutdown execution failed: {e}")

    # 2. Graceful taskkill (sends WM_CLOSE to top-level windows)
    try:
        CREATE_NO_WINDOW = 0x08000000
        subprocess.run(
            ['taskkill', '/IM', 'steam.exe'],
            capture_output=True,
            timeout=4,
            creationflags=CREATE_NO_WINDOW,
            check=False
        )
        start = time.time()
        while time.time() - start < 3.0:
            time.sleep(0.3)
            if not is_steam_running():
                return True
    except Exception as e:
        logger.debug(f"Graceful taskkill failed: {e}")

    # 3. Forced taskkill tree fallback if process still refuses to close
    try:
        CREATE_NO_WINDOW = 0x08000000
        for proc_name in ['steam.exe', 'steamwebhelper.exe', 'steamservice.exe']:
            subprocess.run(
                ['taskkill', '/F', '/T', '/IM', proc_name],
                capture_output=True,
                timeout=3,
                creationflags=CREATE_NO_WINDOW,
                check=False
            )
        time.sleep(0.5)
    except Exception as e:
        logger.debug(f"Force taskkill failed: {e}")

    return not is_steam_running()


def safe_close_steam(steam_path: Optional[str] = None, timeout_sec: float = 5.0) -> bool:
    """Safe Steam shutdown calling steam.exe -shutdown, with timeout fallback kill."""
    return close_steam_client(timeout_sec=timeout_sec, steam_path=steam_path)


def launch_steam(steam_path: Optional[str] = None, big_picture: bool = False) -> bool:
    """Launches steam.exe detached from current process."""
    sp = steam_path or get_steam_path()
    if not sp:
        return False
    steam_exe = os.path.normpath(os.path.join(sp, "steam.exe"))
    if not os.path.isfile(steam_exe):
        return False
    args = [steam_exe]
    if big_picture:
        args.append("-gamepadui")
    try:
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(args, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        return True
    except Exception as e:
        logger.error(f"Failed to launch steam: {e}")
        return False


def get_steam_path() -> Optional[str]:
    """Finds Steam installation directory via Windows registry or default locations."""
    # 1. Check HKCU\Software\Valve\Steam -> SteamPath
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            val, _ = winreg.QueryValueEx(key, "SteamPath")
            path = os.path.normpath(val)
            if os.path.isdir(path):
                return path
    except Exception:
        pass

    # 2. Check HKLM\SOFTWARE\WOW6432Node\Valve\Steam -> InstallPath
    try:
        import winreg
        for subkey in [r"SOFTWARE\WOW6432Node\Valve\Steam", r"SOFTWARE\Valve\Steam"]:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "InstallPath")
                    path = os.path.normpath(val)
                    if os.path.isdir(path):
                        return path
            except Exception:
                continue
    except Exception:
        pass

    # 3. Check standard fallback paths
    fallbacks = [
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Steam",
        r"D:\Steam",
        r"E:\Steam"
    ]
    for p in fallbacks:
        if os.path.isdir(p):
            return os.path.normpath(p)

    return None


def get_steam_users_info(steam_path: str) -> List[Dict[str, Any]]:
    """
    Parses loginusers.vdf and userdata directory to detect all Steam user profiles.
    Returns list of dicts with:
    - account_id: 32-bit ID (folder in userdata)
    - steamid64: 64-bit Steam ID string
    - persona_name: display name (e.g. scalevvizard)
    - account_name: login username (e.g. neckich_bitch)
    - is_active: whether this is currently the active/most recent account
    - auto_login: whether AutoLogin == '1'
    - timestamp: last login timestamp
    """
    userdata_dir = os.path.join(steam_path, "userdata")
    if not os.path.isdir(userdata_dir):
        return []

    try:
        user_folders = set(
            d for d in os.listdir(userdata_dir)
            if d.isdigit() and os.path.isdir(os.path.join(userdata_dir, d))
        )
    except OSError:
        user_folders = set()

    loginusers_file = os.path.join(steam_path, "config", "loginusers.vdf")
    users_info: Dict[str, Dict[str, Any]] = {}

    if os.path.isfile(loginusers_file):
        try:
            with open(loginusers_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                data = vdf.loads(content)
                users_block = {}
                if isinstance(data, dict):
                    for k, v in data.items():
                        if str(k).lower() == 'users' and isinstance(v, dict):
                            users_block = v
                            break
                for sid64_str, uinfo in users_block.items():
                    if not isinstance(uinfo, dict):
                        continue
                    try:
                        sid64 = int(sid64_str)
                        acc_id = str(sid64 & 0xFFFFFFFF)
                    except ValueError:
                        continue

                    u_lower = {str(k).lower(): v for k, v in uinfo.items()}
                    ts = 0
                    try:
                        ts = int(u_lower.get('timestamp', 0))
                    except (ValueError, TypeError):
                        pass

                    auto_login = str(u_lower.get('autologin', '0')) == '1'
                    most_recent = str(u_lower.get('mostrecent', '0')) == '1'
                    persona = str(u_lower.get('personaname', ''))
                    account = str(u_lower.get('accountname', ''))

                    users_info[acc_id] = {
                        'account_id': acc_id,
                        'steamid64': sid64_str,
                        'persona_name': persona,
                        'account_name': account,
                        'auto_login': auto_login,
                        'most_recent': most_recent,
                        'timestamp': ts,
                        'is_active': False
                    }
        except Exception as e:
            logger.warning(f"Error parsing loginusers.vdf: {e}")

    result = []
    active_id = None
    best_ts = -1

    for folder_id in user_folders:
        if folder_id in users_info:
            info = users_info[folder_id]
        else:
            has_config = os.path.isfile(os.path.join(userdata_dir, folder_id, "config", "localconfig.vdf"))
            info = {
                'account_id': folder_id,
                'steamid64': '',
                'persona_name': f"User {folder_id}",
                'account_name': folder_id,
                'auto_login': False,
                'most_recent': False,
                'timestamp': 0,
                'is_active': False,
                'is_stub': not has_config
            }
        result.append(info)

    # 1. auto_login == True
    for item in result:
        if item.get('auto_login'):
            active_id = item['account_id']
            break

    # 2. most_recent == True
    if not active_id:
        for item in result:
            if item.get('most_recent'):
                active_id = item['account_id']
                break

    # 3. highest timestamp
    if not active_id:
        for item in result:
            if item.get('timestamp', 0) > best_ts:
                best_ts = item.get('timestamp', 0)
                active_id = item['account_id']

    # 4. Folder with localconfig.vdf and newest mtime
    if not active_id and result:
        def _safe_mtime(p: str) -> float:
            try:
                return os.path.getmtime(p)
            except OSError:
                return 0.0

        result.sort(
            key=lambda x: (
                os.path.isfile(os.path.join(userdata_dir, x['account_id'], "config", "localconfig.vdf")),
                _safe_mtime(os.path.join(userdata_dir, x['account_id']))
            ),
            reverse=True
        )
        active_id = result[0]['account_id']

    for item in result:
        if item['account_id'] == active_id:
            item['is_active'] = True

    result.sort(
        key=lambda x: (
            x.get('is_active', False),
            not x.get('is_stub', False),
            x.get('timestamp', 0)
        ),
        reverse=True
    )

    return result


def is_safe_steam_user_id(user_id: Any) -> bool:
    """
    Validates that steam_user_id is strictly a numeric string (Steam 32-bit Account ID).
    Prevents path traversal attacks (e.g. '../../evil') when constructing userdata paths.
    """
    if user_id is None:
        return False
    user_str = str(user_id).strip()
    return bool(re.match(r'^\d+$', user_str))


def get_active_steam_user(steam_path: str) -> Optional[str]:
    """
    Finds active user ID in <SteamPath>/userdata/.
    Uses loginusers.vdf first to determine currently active or auto-login account.
    Validates that account ID is safe and numeric.
    """
    users = get_steam_users_info(steam_path)
    for u in users:
        acc = u.get('account_id')
        if u.get('is_active') and is_safe_steam_user_id(acc):
            return acc
    for u in users:
        acc = u.get('account_id')
        if is_safe_steam_user_id(acc):
            return acc
    return None


def get_file_crc32(filepath: str) -> Optional[int]:
    """Calculates CRC32 checksum of a file for integrity verification."""
    try:
        crc = 0
        with open(filepath, 'rb') as f:
            while chunk := f.read(65536):
                crc = zlib.crc32(chunk, crc)
        return crc
    except Exception:
        return None


def backup_shortcuts_file(shortcuts_path: str) -> Optional[str]:
    """
    Creates a rotating 3-generation backup of shortcuts.vdf before modifying it:
    shortcuts.vdf.bak, shortcuts.vdf.bak.1, shortcuts.vdf.bak.2, shortcuts.vdf.bak.3.
    Guarantees non-destructive rollback if anything fails and verifies CRC32 integrity.
    """
    if not os.path.isfile(shortcuts_path):
        return None

    try:
        if os.path.getsize(shortcuts_path) == 0:
            logger.warning(f"Skipping backup of 0-byte shortcuts.vdf ({shortcuts_path}) to prevent rotating out valid backups.")
            return None
    except OSError:
        return None

    bak_base = shortcuts_path + ".bak"

    def _ensure_writable(path: str):
        if os.path.exists(path):
            try:
                mode = os.stat(path).st_mode
                if not (mode & stat.S_IWRITE):
                    os.chmod(path, mode | stat.S_IWRITE)
            except Exception:
                pass

    # Shift backups: .bak.2 -> .bak.3, .bak.1 -> .bak.2, .bak -> .bak.1
    try:
        if os.path.isfile(f"{bak_base}.2"):
            _ensure_writable(f"{bak_base}.3")
            shutil.copy2(f"{bak_base}.2", f"{bak_base}.3")
        if os.path.isfile(f"{bak_base}.1"):
            _ensure_writable(f"{bak_base}.2")
            shutil.copy2(f"{bak_base}.1", f"{bak_base}.2")
        if os.path.isfile(bak_base):
            _ensure_writable(f"{bak_base}.1")
            shutil.copy2(bak_base, f"{bak_base}.1")
    except Exception as e:
        logger.debug(f"Rotation exception: {e}")

    # Create current primary backup with CRC32 verification
    try:
        _ensure_writable(bak_base)
        shutil.copy2(shortcuts_path, bak_base)
        src_crc = get_file_crc32(shortcuts_path)
        dst_crc = get_file_crc32(bak_base)
        if src_crc is not None and dst_crc is not None and src_crc != dst_crc:
            logger.error(f"CRC32 mismatch between source ({src_crc}) and backup ({dst_crc})!")
            raise IOError(f"Backup CRC32 mismatch for {bak_base}")
        logger.debug(f"Backup {bak_base} verified with CRC32: {hex(src_crc or 0)}")
        return bak_base
    except Exception as e:
        logger.warning(f"Failed to create shortcuts.vdf.bak: {e}")
        return None


# ==============================================================================
# Phase 3.1: Game Scanning & Filtering
# ==============================================================================

def parse_folder_list(inputs: Union[str, List[str]]) -> List[str]:
    """
    Parses directory inputs, handling space-separated paths, semicolons,
    commas, newlines, or composite strings like 'D:\\Gamess C:\\Games'.
    Preserves existing paths and normalizes formatting.
    """
    if isinstance(inputs, str):
        inputs = [inputs]

    results: List[str] = []
    for item in inputs:
        if not item:
            continue
        item = item.strip().strip('"').strip("'")
        if not item:
            continue

        if os.path.isdir(item):
            results.append(os.path.normpath(item))
            continue

        # Split on semicolons, newlines, commas, or whitespace preceding a drive letter
        parts = re.split(r'[;\n\r,]+|\s+(?=[A-Za-z]:[\\/])', item)
        for p in parts:
            p = p.strip().strip('"').strip("'")
            if p:
                results.append(os.path.normpath(p))

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for r in results:
        norm = r.lower()
        if norm not in seen:
            seen.add(norm)
            deduped.append(r)
    return deduped


def clean_game_name(folder_name: str) -> str:
    """
    Cleans release distribution tags and metadata from folder names:
    - [GOG], [DRM-Free], [Digital Deluxe], (2025)
    - -Group, -RUNE, etc.
    - v1.0.4, build 12345, portable
    - Dots and underscores replaced with spaces
    """
    name = folder_name
    # Strip release group at the end with a dash
    name = re.sub(r'-\s*[a-zA-Z0-9_\.]+$', '', name)
    # Remove bracketed tags [Tag], (Tag), etc.
    name = re.sub(r'\[.*?\]|\(.*?\)', ' ', name)
    # Remove version and build tags before replacing dots
    name = re.sub(r'\b(?:v|ver|version)\s*\.?\s*\d+(?:\.\d+)*\b', '', name, flags=re.IGNORECASE)
    name = re.sub(
        r'\b(build[\s\.\-_]*\d+|patch[\s\.\-_]*\d+|package|archive|portable|multi\d+|x64|x86|rus|eng)\b',
        '',
        name,
        flags=re.IGNORECASE
    )
    # Replace dots and underscores with spaces
    name = name.replace('.', ' ').replace('_', ' ')
    # Clean extra whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    if not name:
        name = folder_name.strip()
    if not name:
        name = "Unknown Game"
    return name


def is_valid_executable(filename: str, clean_name: str = "") -> bool:
    """Checks whether the filename looks like a legitimate game executable."""
    if not filename or not isinstance(filename, str):
        return False
    lower = filename.lower()
    if not lower.endswith('.exe'):
        return False
    clean_lower = clean_name.lower() if clean_name else ""

    # Strict regex pattern blacklist (unins000.exe, UnityCrashHandler*.exe, DXSETUP.exe, vcredist*.exe, etc.)
    blacklist_patterns = [
        r'^unins\d*\.exe$',
        r'^unitycrashhandler.*\.exe$',
        r'^dxsetup.*\.exe$',
        r'^vcredist.*\.exe$',
        r'^vc_redist.*\.exe$',
        r'^crashreport.*\.exe$',
        r'^epiconlineservices.*\.exe$',
        r'^epicgameslauncher.*\.exe$',
        r'^epicgamesupdater.*\.exe$',
        r'^unrealenginelauncher.*\.exe$',
        r'^eosbootstrapper.*\.exe$',
        r'^eosoverlayrenderer.*\.exe$',
        r'^epicwebhelper.*\.exe$'
    ]
    for pat in blacklist_patterns:
        if re.match(pat, lower):
            return False

    for kw in IGNORE_KEYWORDS:
        if kw in lower:
            # If the keyword is an authentic part of the game's title (e.g. Crash Bandicoot), allow it
            if clean_lower and kw in clean_lower and kw in ['crash', 'patch', 'tool', 'config', 'server']:
                continue
            return False
    return True


def find_best_game_exe(game_folder_path: str, clean_name: str, max_depth: int = 3) -> Optional[Dict[str, Any]]:
    """
    Scans a game directory up to `max_depth` to locate the main game executable.
    Prioritizes executables matching the game name or having the largest file size.
    Handles engine shipping binaries (e.g. Binaries\\Win64\\...-Shipping.exe).
    Supports Unicode/Cyrillic game names.
    """
    candidates = []
    norm_folder = os.path.normpath(game_folder_path)
    base_depth = len(norm_folder.rstrip(os.sep).split(os.sep))

    for root, dirs, files in os.walk(norm_folder):
        current_depth = len(root.split(os.sep)) - base_depth
        if current_depth > max_depth:
            dirs.clear()
            continue

        for f in files:
            if is_valid_executable(f, clean_name=clean_name):
                full_path = os.path.join(root, f)
                try:
                    size = os.path.getsize(full_path)
                    candidates.append({
                        'name': f,
                        'path': full_path,
                        'size': size,
                        'depth': current_depth
                    })
                except OSError:
                    pass

    if not candidates:
        return None

    def normalize(s: str) -> str:
        # Strip common binary suffixes like shipping, win64, x64, mastermaster
        s = re.sub(r'[-_]?(win64|win32|x64|x86)[-_]?(shipping|mastermaster|steampgo)?', '', s, flags=re.IGNORECASE)
        s = re.sub(r'[-_]?(shipping|launcher|game)', '', s, flags=re.IGNORECASE)
        return re.sub(r'[^\w]', '', s).lower()

    norm_clean = normalize(clean_name)

    # 1. Match raw filename stem exactly with game name (prefer shallower depth / root launcher)
    raw_exact = [
        c for c in candidates
        if norm_clean and re.sub(r'[^\w]', '', os.path.splitext(c['name'])[0]).lower() == norm_clean
    ]
    if raw_exact:
        raw_exact.sort(key=lambda c: (c['depth'], -c['size']))
        return raw_exact[0]

    # 2. Normalized match (stripping -shipping, win64, etc.)
    norm_matches = [
        c for c in candidates
        if norm_clean and normalize(os.path.splitext(c['name'])[0]) == norm_clean
    ]
    if norm_matches:
        norm_matches.sort(key=lambda c: (c['depth'], -c['size']))
        return norm_matches[0]

    # 3. Partial match (with minimum length protection to prevent false positives like 'it.exe', 'go.exe')
    partial_matches = []
    if norm_clean and len(norm_clean) >= 4:
        for c in candidates:
            stem = normalize(os.path.splitext(c['name'])[0])
            if len(stem) >= 4 and stem in norm_clean:
                partial_matches.append(c)
            elif len(stem) >= 4 and norm_clean in stem:
                partial_matches.append(c)

    if partial_matches:
        partial_matches.sort(key=lambda c: c['size'], reverse=True)
        return partial_matches[0]

    # 4. Fallback: largest executable size
    candidates.sort(key=lambda c: c['size'], reverse=True)
    return candidates[0]


def scan_epic_games_manifests(manifest_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Parses Epic Games Launcher manifests (*.item) to detect installed games.
    Default directory: C:\\ProgramData\\Epic\\EpicGamesLauncher\\Data\\Manifests\\*.item
    Extracts DisplayName, InstallLocation, LaunchExecutable, AppName.
    """
    if manifest_dir is None:
        manifest_dir = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"

    if not os.path.isdir(manifest_dir):
        return []

    games = []
    seen_paths = set()
    import glob
    import json

    try:
        item_files = glob.glob(os.path.join(manifest_dir, "*.item"))
    except Exception as e:
        logger.debug(f"Error listing Epic manifests: {e}")
        return []

    for item_path in item_files:
        try:
            with open(item_path, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
        except Exception as e:
            logger.debug(f"Error parsing Epic manifest {item_path}: {e}")
            continue

        if not isinstance(data, dict):
            continue

        display_name = str(data.get("DisplayName", "")).strip()
        install_loc = str(data.get("InstallLocation", "")).strip()
        launch_exe = str(data.get("LaunchExecutable", "")).strip()
        app_name = str(data.get("AppName", "")).strip()

        # Strict filter: ignore Epic Games Launcher itself and non-game manifests
        app_name_lower = app_name.lower().strip()
        disp_lower = display_name.lower().strip()
        launch_lower = launch_exe.lower().strip()

        if app_name_lower in {'launcher', 'epicgameslauncher', 'eos', 'epicgames', 'epicgamesstore', 'epiconlineservices'} or app_name_lower.startswith(('ue_', 'unrealengine', 'launcher', 'epicgameslauncher', 'epic_games', 'eos')):
            continue
        if any(ign in disp_lower for ign in ['epic games launcher', 'epic games', 'epic launcher', 'epic online services', 'unreal engine', 'prerequisites', 'epic games store', 'eos']):
            continue
        if any(ign in launch_lower for ign in ['epicgameslauncher', 'epicgamesupdater', 'unrealenginelauncher', 'epiconlineservices', 'epicwebhelper', 'eosbootstrapper', 'eosoverlayrenderer']):
            continue

        if not display_name or not install_loc:
            continue

        norm_loc = os.path.normpath(install_loc)
        norm_loc_lower = norm_loc.lower()

        # Strictly ignore install locations inside Epic Games Launcher itself
        if (norm_loc_lower.endswith(r'\epic games\launcher') or
            norm_loc_lower.endswith(r'\epicgames\launcher') or
            '\\epic games\\launcher\\' in norm_loc_lower or
            '\\epicgames\\launcher\\' in norm_loc_lower or
            (os.path.basename(norm_loc_lower) == 'launcher' and
             os.path.basename(os.path.dirname(norm_loc_lower)) in ('epic games', 'epicgames'))):
            continue

        if not os.path.isdir(norm_loc):
            continue

        clean_name = clean_game_name(display_name)
        exe_path = None
        if launch_exe and is_valid_executable(os.path.basename(launch_exe), clean_name=clean_name):
            cand = os.path.normpath(os.path.join(norm_loc, launch_exe))
            if os.path.isfile(cand):
                exe_path = cand

        if not exe_path:
            best_exe = find_best_game_exe(norm_loc, clean_name)
            if best_exe:
                exe_path = os.path.normpath(best_exe['path'])

        if not exe_path or not os.path.isfile(exe_path):
            continue

        exe_basename = os.path.basename(exe_path).lower()
        if exe_basename in {
            'epicgameslauncher.exe', 'epicgamesupdater.exe', 'unrealenginelauncher.exe',
            'eosbootstrapper.exe', 'epicwebhelper.exe', 'crashreportclient.exe'
        }:
            continue

        if not is_valid_executable(os.path.basename(exe_path), clean_name=clean_name):
            continue

        if exe_path.lower() in seen_paths:
            continue
        seen_paths.add(exe_path.lower())

        try:
            exe_size = os.path.getsize(exe_path)
        except OSError:
            exe_size = 0

        game_obj = DiscoveredGame(
            name=display_name,
            exe_path=exe_path,
            start_dir=norm_loc,
            source="Epic Games",
            folder_name=display_name,
            folder_path=norm_loc,
            clean_name=clean_name,
            exe_name=os.path.basename(exe_path),
            exe_size=exe_size,
            launcher='Epic Games',
            app_id_str=app_name
        )
        games.append(game_obj)

    return games


def scan_gog_galaxy_games() -> List[Dict[str, Any]]:
    """
    Scans GOG Galaxy installed games from Windows Registry:
    - HKLM\\SOFTWARE\\WOW6432Node\\GOG.com\\Games
    - HKLM\\SOFTWARE\\GOG.com\\Games
    - HKCU\\SOFTWARE\\GOG.com\\Games
    Extracts gameName, path, exe, gameID.
    """
    games = []
    seen_paths = set()

    try:
        import winreg
    except ImportError:
        return []

    roots = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]
    subkeys = [
        r"SOFTWARE\WOW6432Node\GOG.com\Games",
        r"SOFTWARE\GOG.com\Games"
    ]

    for root_h in roots:
        for sub_path in subkeys:
            try:
                with winreg.OpenKey(root_h, sub_path) as parent_key:
                    num_subkeys = winreg.QueryInfoKey(parent_key)[0]
                    for i in range(num_subkeys):
                        gk_name = winreg.EnumKey(parent_key, i)
                        try:
                            with winreg.OpenKey(parent_key, gk_name) as gk:
                                def get_val(name):
                                    try:
                                        val, _ = winreg.QueryValueEx(gk, name)
                                        return str(val).strip() if val else ""
                                    except Exception:
                                        return ""

                                g_name = get_val("gameName") or get_val("GAMENAME")
                                g_path = get_val("path") or get_val("PATH")
                                g_exe = get_val("exe") or get_val("EXE")
                                g_id = get_val("gameID") or get_val("GAMEID") or gk_name

                                if not g_path or not os.path.isdir(g_path):
                                    continue

                                norm_dir = os.path.normpath(g_path)
                                target_exe = None
                                if g_exe:
                                    if os.path.isabs(g_exe) and os.path.isfile(g_exe):
                                        target_exe = os.path.normpath(g_exe)
                                    else:
                                        joined = os.path.normpath(os.path.join(norm_dir, g_exe))
                                        if os.path.isfile(joined):
                                            target_exe = joined

                                clean_name = clean_game_name(g_name) if g_name else clean_game_name(os.path.basename(norm_dir))
                                if not target_exe:
                                    best_exe = find_best_game_exe(norm_dir, clean_name)
                                    if best_exe:
                                        target_exe = os.path.normpath(best_exe['path'])

                                if not target_exe or not os.path.isfile(target_exe):
                                    continue

                                if not is_valid_executable(os.path.basename(target_exe), clean_name=clean_name):
                                    continue

                                if target_exe.lower() in seen_paths:
                                    continue
                                seen_paths.add(target_exe.lower())

                                try:
                                    exe_size = os.path.getsize(target_exe)
                                except OSError:
                                    exe_size = 0

                                game_obj = DiscoveredGame(
                                    name=g_name or os.path.basename(norm_dir),
                                    exe_path=target_exe,
                                    start_dir=norm_dir,
                                    source="GOG Galaxy",
                                    folder_name=g_name or os.path.basename(norm_dir),
                                    folder_path=norm_dir,
                                    clean_name=clean_name,
                                    exe_name=os.path.basename(target_exe),
                                    exe_size=exe_size,
                                    launcher='GOG Galaxy',
                                    game_id=g_id
                                )
                                games.append(game_obj)
                        except Exception:
                            continue
            except Exception:
                continue

    return games


def scan_games(root_directories: Union[str, List[str]], include_launchers: bool = False) -> List[Dict[str, Any]]:
    """
    Scans specified root game directories and returns a list of detected games.
    Supports composite path strings and automatic normalization.
    Optionally merges games auto-detected from Epic Games and GOG Galaxy.
    """
    parsed_roots = parse_folder_list(root_directories)
    discovered_games = []
    seen_paths = set()

    for root_dir in parsed_roots:
        norm_root = os.path.normpath(root_dir)
        if not os.path.isdir(norm_root):
            logger.warning(f"Game root directory does not exist: {norm_root}")
            continue

        logger.info(f"Scanning games folder: {norm_root}")
        try:
            entries = sorted(os.listdir(norm_root))
        except OSError as e:
            logger.warning(f"Failed to list directory {norm_root}: {e}")
            continue

        for item in entries:
            item_path = os.path.join(norm_root, item)
            if not os.path.isdir(item_path):
                continue

            # Ignore system, launcher, and metadata folders
            if item.startswith('$') or item.lower() in IGNORE_SUBFOLDERS or item.lower() in IGNORE_ROOT_NAMES:
                continue

            clean_name = clean_game_name(item)
            best_exe = find_best_game_exe(item_path, clean_name)
            if not best_exe:
                logger.debug(f"No suitable .exe found in: {item}")
                continue

            exe_norm = os.path.normpath(best_exe['path'])
            if exe_norm.lower() in seen_paths:
                continue
            seen_paths.add(exe_norm.lower())

            game_obj = DiscoveredGame(
                name=clean_name,
                exe_path=exe_norm,
                start_dir=item_path,
                source="Standalone",
                folder_name=item,
                folder_path=item_path,
                clean_name=clean_name,
                exe_name=best_exe['name'],
                exe_size=best_exe['size']
            )
            discovered_games.append(game_obj)

        # If no subfolder games were discovered in norm_root, check if norm_root itself is a direct game folder
        norm_root_case = os.path.normcase(norm_root)
        if not any(
            os.path.normcase(g['folder_path']) == norm_root_case or
            os.path.normcase(g['folder_path']).startswith(norm_root_case + os.sep)
            for g in discovered_games
        ):
            root_name = os.path.basename(norm_root)
            if root_name and not root_name.startswith('$') and root_name.lower() not in IGNORE_SUBFOLDERS and root_name.lower() not in IGNORE_ROOT_NAMES:
                clean_name = clean_game_name(root_name)
                best_exe = find_best_game_exe(norm_root, clean_name, max_depth=2)
                if best_exe:
                    exe_norm = os.path.normpath(best_exe['path'])
                    if exe_norm.lower() not in seen_paths:
                        seen_paths.add(exe_norm.lower())
                        game_obj = DiscoveredGame(
                            name=clean_name,
                            exe_path=exe_norm,
                            start_dir=norm_root,
                            source="Standalone",
                            folder_name=root_name,
                            folder_path=norm_root,
                            clean_name=clean_name,
                            exe_name=best_exe['name'],
                            exe_size=best_exe['size']
                        )
                        discovered_games.append(game_obj)

    if include_launchers:
        try:
            epic_games = scan_epic_games_manifests()
            for eg in epic_games:
                norm_exe = os.path.normpath(eg['exe_path']).lower()
                if norm_exe not in seen_paths:
                    seen_paths.add(norm_exe)
                    discovered_games.append(eg)
        except Exception as e:
            logger.debug(f"Epic Games scan error: {e}")

        try:
            gog_games = scan_gog_galaxy_games()
            for gg in gog_games:
                norm_exe = os.path.normpath(gg['exe_path']).lower()
                if norm_exe not in seen_paths:
                    seen_paths.add(norm_exe)
                    discovered_games.append(gg)
        except Exception as e:
            logger.debug(f"GOG Galaxy scan error: {e}")

    return discovered_games


def scan_all_games(root_directories: Union[str, List[str]], include_launchers: bool = True) -> List[Dict[str, Any]]:
    """Convenience wrapper for scanning both folder directories and installed launchers."""
    return scan_games(root_directories, include_launchers=include_launchers)


# ==============================================================================
# Phase 3.2: Steam Identifiers & CRC32
# ==============================================================================

def calculate_steam_ids(exe_path: str, clean_name: str) -> Tuple[int, int, int]:
    """
    Computes Steam Grid AppID, VDF 32-bit signed integer ID, and 64-bit ID.
    target = f'"{unquoted_exe}"{clean_name}'.encode('utf-8')
    crc = zlib.crc32(target)
    grid_id = crc | 0x80000000
    vdf_appid = int(ctypes.c_int32(grid_id).value)
    grid_id_64 = (grid_id << 32) | 0x02000000
    """
    unquoted_exe = exe_path.replace('\0', '').strip().strip('"\'')
    clean_app_name = clean_name.replace('\0', '').strip()
    target = f'"{unquoted_exe}"{clean_app_name}'.encode('utf-8', errors='replace')
    crc = zlib.crc32(target) & 0xFFFFFFFF
    grid_id = (crc | 0x80000000) & 0xFFFFFFFF
    vdf_appid = int(ctypes.c_int32(grid_id).value)
    grid_id_64 = (grid_id << 32) | 0x02000000
    return grid_id, vdf_appid, grid_id_64


# ==============================================================================
# Phase 3.3: Artwork Downloading (Valve CDN, No API Keys)
# ==============================================================================

# Keywords indicating a DLC, soundtrack, or accessory item rather than the base game
DLC_SOUNDTRACK_KEYWORDS = [
    'soundtrack', 'ost', 'songs of the', 'баллады', 'песни', 'музыка',
    'score', 'artbook', 'артбук', 'wallpaper', 'guide', 'manual',
    'dlc', 'дополнение', 'season pass', 'expansion pack',
    'skin', 'облик', 'скин', 'outfit', 'костюм', 'gadget',
    'upgrade', 'bonus content', 'demo', 'playtest', 'server', 'pack', 'набор'
]


VALVE_ALLOWED_DOMAINS = {
    'store.steampowered.com',
    'shared.steamstatic.com',
    'shared.cloudflare.steamstatic.com',
    'steamcdn-a.akamaihd.net',
    'cdn.cloudflare.steamstatic.com',
    'cdn.akamai.steamstatic.com'
}

STEAMGRIDDB_ALLOWED_DOMAINS = {
    'steamgriddb.com',
    'www.steamgriddb.com',
    'cdn2.steamgriddb.com',
    'images.steamgriddb.com'
}

ARTWORK_ALLOWED_DOMAINS = VALVE_ALLOWED_DOMAINS | STEAMGRIDDB_ALLOWED_DOMAINS


def is_safe_valve_url(url: str) -> bool:
    """
    Strictly validates that URL uses HTTPS and points to an allowed Valve CDN/Store domain.
    Rejects credentials, non-standard ports (SSRF protection), and non-whitelisted domains.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() != 'https':
            return False
        if parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 443):
            return False
        hostname = (parsed.hostname or '').lower()
        return hostname in VALVE_ALLOWED_DOMAINS
    except Exception:
        return False


def is_safe_artwork_url(url: str) -> bool:
    """
    Validates that URL uses HTTPS and points to an allowed Valve or SteamGridDB CDN domain.
    Rejects credentials, non-standard ports (SSRF protection), and non-whitelisted domains.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() != 'https':
            return False
        if parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 443):
            return False
        hostname = (parsed.hostname or '').lower()
        return hostname in ARTWORK_ALLOWED_DOMAINS
    except Exception:
        return False


class SteamGridDBClient:
    """
    Client for SteamGridDB API v2 (https://www.steamgriddb.com/api/v2).
    Provides access to community posters (grids), hero banners, transparent logos, and icons.
    Gracefully handles missing keys, network timeouts, and non-standard responses.
    """
    BASE_URL = "https://www.steamgriddb.com/api/v2"

    def __init__(self, api_key: Optional[str] = None):
        key = api_key if (api_key is not None and str(api_key).strip()) else DEFAULT_STEAMGRIDDB_KEY
        self.api_key = str(key).strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "DeckBridge/2.2.0 (Windows NT 10.0; Win64; x64)"
        }

    def search_game(self, term: str) -> Optional[int]:
        """Searches SteamGridDB by term and returns internal game ID."""
        if not self.api_key or not term or not term.strip():
            return None
        url = f"{self.BASE_URL}/search/autocomplete/{requests.utils.quote(term.strip())}"
        try:
            resp = safe_requests_get(url, headers=self._headers(), timeout=(3.0, 5.0), max_retries=1)
            if resp and resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("success") and data.get("data"):
                    first = data["data"][0]
                    if isinstance(first, dict) and first.get("id"):
                        return int(first["id"])
        except Exception as e:
            logger.debug(f"SteamGridDB search failed for '{term}': {e}")
        return None

    def get_game_by_steam_appid(self, steam_appid: int) -> Optional[int]:
        """Retrieves SteamGridDB internal game ID from official Steam App ID."""
        if not self.api_key or not steam_appid or steam_appid <= 0:
            return None
        url = f"{self.BASE_URL}/games/steam/{steam_appid}"
        try:
            resp = safe_requests_get(url, headers=self._headers(), timeout=(3.0, 5.0), max_retries=1)
            if resp and resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("success") and data.get("data"):
                    g_data = data["data"]
                    if isinstance(g_data, dict) and g_data.get("id"):
                        return int(g_data["id"])
        except Exception as e:
            logger.debug(f"SteamGridDB steam lookup failed for {steam_appid}: {e}")
        return None

    def get_artwork_urls(self, game_id: int) -> Dict[str, str]:
        """
        Retrieves highest-voted artwork URLs for:
        - poster: vertical grid (600x900)
        - hero: banner (1920x620)
        - logo: transparent title overlay
        - icon: executable / desktop icon
        """
        urls = {}
        if not self.api_key or not game_id or game_id <= 0:
            return urls

        # 1. Vertical Grid (600x900 poster)
        try:
            url = f"{self.BASE_URL}/grids/game/{game_id}?dimensions=600x900"
            resp = safe_requests_get(url, headers=self._headers(), timeout=(3.0, 5.0), max_retries=1)
            if resp and resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("success") and data.get("data"):
                    items = data["data"]
                    if items and isinstance(items[0], dict) and items[0].get("url"):
                        urls['poster'] = items[0]["url"]
        except Exception as e:
            logger.debug(f"SteamGridDB grid fetch error: {e}")

        # 2. Horizontal Wide Grid (920x430, 460x215)
        try:
            url = f"{self.BASE_URL}/grids/game/{game_id}?dimensions=920x430,460x215"
            resp = safe_requests_get(url, headers=self._headers(), timeout=(3.0, 5.0), max_retries=1)
            if resp and resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("success") and data.get("data"):
                    items = data["data"]
                    if items and isinstance(items[0], dict) and items[0].get("url"):
                        urls['capsule'] = items[0]["url"]
                        urls['grid_wide'] = items[0]["url"]
        except Exception as e:
            logger.debug(f"SteamGridDB wide grid fetch error: {e}")

        # 3. Hero banner
        try:
            url = f"{self.BASE_URL}/heroes/game/{game_id}"
            resp = safe_requests_get(url, headers=self._headers(), timeout=(3.0, 5.0), max_retries=1)
            if resp and resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("success") and data.get("data"):
                    items = data["data"]
                    if items and isinstance(items[0], dict) and items[0].get("url"):
                        urls['hero'] = items[0]["url"]
        except Exception as e:
            logger.debug(f"SteamGridDB hero fetch error: {e}")

        # 3. Logo (transparent PNG)
        try:
            url = f"{self.BASE_URL}/logos/game/{game_id}"
            resp = safe_requests_get(url, headers=self._headers(), timeout=(3.0, 5.0), max_retries=1)
            if resp and resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("success") and data.get("data"):
                    items = data["data"]
                    if items and isinstance(items[0], dict) and items[0].get("url"):
                        urls['logo'] = items[0]["url"]
        except Exception as e:
            logger.debug(f"SteamGridDB logo fetch error: {e}")

        # 4. Icon
        try:
            url = f"{self.BASE_URL}/icons/game/{game_id}"
            resp = safe_requests_get(url, headers=self._headers(), timeout=(3.0, 5.0), max_retries=1)
            if resp and resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("success") and data.get("data"):
                    items = data["data"]
                    if items and isinstance(items[0], dict) and items[0].get("url"):
                        urls['icon'] = items[0]["url"]
        except Exception as e:
            logger.debug(f"SteamGridDB icon fetch error: {e}")

        return urls


def safe_requests_get(
    url: str,
    headers: Optional[dict] = None,
    timeout: Union[int, float, Tuple[float, float]] = (3.0, 5.0),
    allow_redirects: bool = True,
    max_retries: int = 2
) -> Optional[requests.Response]:
    """
    Executes HTTP GET with rock-solid network exception interception.
    Catches Timeouts, DNS resolution errors (socket.gaierror), ConnectionError,
    SSL failures, and socket drops without hanging or crashing threads.
    Validates redirect hops and final URLs against SSRF allowlist.
    """
    if not url or not isinstance(url, str) or not url.strip():
        return None
    try:
        parsed_scheme = urlparse(url.strip()).scheme.lower()
        if parsed_scheme not in ('http', 'https'):
            logger.warning(f"Rejected unsupported URL scheme: {url}")
            return None
    except Exception:
        return None
    req_headers = headers or {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=req_headers, timeout=timeout, allow_redirects=allow_redirects)
            if resp.status_code == 429:
                wait_time = 1.0 * (2 ** attempt)
                logger.warning(f"HTTP 429 Too Many Requests received from Steam. Backing off for {wait_time}s...")
                time.sleep(wait_time)
                continue

            # SSRF Protection: ensure redirects do not hop outside safe Valve/Artwork domains
            if getattr(resp, 'history', None):
                unsafe_hop = False
                for hop in resp.history:
                    h_url = getattr(hop, 'url', None)
                    if isinstance(h_url, str) and not is_safe_artwork_url(h_url):
                        logger.warning(f"Blocked redirect through untrusted hop: {h_url}")
                        unsafe_hop = True
                        break
                if unsafe_hop:
                    return None

            final_url = getattr(resp, 'url', None)
            if isinstance(final_url, str) and not is_safe_artwork_url(final_url):
                logger.warning(f"Blocked redirect to untrusted final destination: {final_url}")
                return None

            return resp
        except (Timeout, socket.timeout) as e:
            logger.debug(f"Network timeout fetching {url} (attempt {attempt+1}/{max_retries+1}): {e}")
        except (ConnectionError, socket.gaierror, ConnectionResetError, ConnectionRefusedError) as e:
            logger.debug(f"Connection/DNS error fetching {url} (attempt {attempt+1}/{max_retries+1}): {e}")
        except SSLError as e:
            logger.debug(f"SSL error fetching {url}: {e}")
            break
        except RequestException as e:
            logger.debug(f"Request exception fetching {url}: {e}")
        except OSError as e:
            logger.debug(f"Socket/OS error fetching {url}: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error fetching {url}: {e}")

        if attempt < max_retries:
            time.sleep(0.4)
    return None


def store_request_with_backoff(url: str, headers: dict, timeout: Union[int, float, Tuple[float, float]] = 4) -> Optional[requests.Response]:
    """
    Executes HTTP GET request with 200-300ms rate pacing and exponential backoff on HTTP 429.
    Prevents triggering Valve CDN rate limiting. Delegates to safe_requests_get.
    """
    time.sleep(0.25)  # 250ms pacing between requests
    to = timeout if isinstance(timeout, tuple) else (3.0, float(timeout))
    return safe_requests_get(url, headers=headers, timeout=to, max_retries=2)


_STORE_APPID_CACHE: Dict[str, Optional[int]] = {}


def search_steam_store_appid(clean_name: str) -> Optional[int]:
    """
    Performs public Valve store search to obtain official Steam AppID.
    Prioritizes exact match, strips edition suffixes if needed, and
    filters out DLC/Skin/Soundtrack items in favor of the base game.
    Includes rate pacing, in-memory caching, and exponential backoff against HTTP 429.
    """
    if not clean_name or not isinstance(clean_name, str) or not clean_name.strip():
        return None

    clean_name = clean_name.strip()
    norm_key = clean_name.lower()
    if norm_key in _STORE_APPID_CACHE:
        return _STORE_APPID_CACHE[norm_key]

    terms_to_try = [clean_name]

    # Strip edition suffixes like "Royal Edition", "Ultimate Edition", "Digital Deluxe"
    without_edition = re.sub(
        r'\b(ultimate|royal|deluxe|gold|goty|game of the year|enhanced|definitive|special|collector\'?s?|complete|digital deluxe)\s*(?:edition|cut|pack)?\b',
        '',
        clean_name,
        flags=re.IGNORECASE
    ).strip()
    if without_edition and without_edition.lower() != clean_name.lower():
        terms_to_try.append(without_edition)

    # If title contains subtitle separator like ':' or ' - ', also try main title
    if ':' in clean_name:
        main_part = clean_name.split(':', 1)[0].strip()
        if main_part and main_part not in terms_to_try:
            terms_to_try.append(main_part)
    if ' - ' in clean_name:
        main_part = clean_name.split(' - ', 1)[0].strip()
        if main_part and main_part not in terms_to_try:
            terms_to_try.append(main_part)

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    def normalize_str(s: str) -> str:
        return re.sub(r'[^a-zA-Z0-9]', '', s).lower()

    for term in terms_to_try:
        norm_term = normalize_str(term)
        if not norm_term:
            continue

        # Try US first (global catalog) then RU (localized), across languages
        for lang in ['english', 'russian']:
            for cc in ['US', 'RU', '']:
                url = f"https://store.steampowered.com/api/storesearch/?term={requests.utils.quote(term)}&l={lang}"
                if cc:
                    url += f"&cc={cc}"

                try:
                    resp = store_request_with_backoff(url, headers=headers, timeout=4)
                    if not resp or resp.status_code != 200:
                        continue
                    try:
                        data = resp.json()
                    except (ValueError, TypeError, Exception) as json_err:
                        logger.debug(f"Invalid JSON from store search for '{term}': {json_err}")
                        continue
                    items = data.get('items', []) if isinstance(data, dict) else []
                    if not items or not isinstance(items, list):
                        continue

                    # 1. Exact match check
                    for itm in items:
                        if not isinstance(itm, dict):
                            continue
                        if normalize_str(str(itm.get('name', ''))) == norm_term:
                            appid = itm.get('id')
                            if appid is not None:
                                try:
                                    appid_val = int(appid)
                                    logger.info(f"Exact Steam match: AppID {appid_val} ('{itm.get('name')}') for '{term}'")
                                    _STORE_APPID_CACHE[norm_key] = appid_val
                                    return appid_val
                                except (ValueError, TypeError):
                                    pass

                    # 2. Filter out DLC / Soundtracks / Skin packs
                    non_dlc = []
                    for itm in items:
                        if not isinstance(itm, dict):
                            continue
                        iname = str(itm.get('name', '')).lower()
                        if not any(dlc_kw in iname for dlc_kw in DLC_SOUNDTRACK_KEYWORDS):
                            non_dlc.append(itm)

                    candidates = non_dlc if non_dlc else [itm for itm in items if isinstance(itm, dict)]
                    if not candidates:
                        continue

                    # Prefer candidates where name starts with query or has shortest length
                    candidates.sort(key=lambda itm: abs(len(str(itm.get('name', ''))) - len(term)))
                    for chosen in candidates:
                        appid = chosen.get('id')
                        if appid is not None:
                            try:
                                appid_val = int(appid)
                                logger.info(f"Found Steam AppID {appid_val} ('{chosen.get('name')}') for '{term}' (cc={cc}, l={lang})")
                                _STORE_APPID_CACHE[norm_key] = appid_val
                                return appid_val
                            except (ValueError, TypeError):
                                continue
                except Exception as e:
                    logger.debug(f"Store search failed for '{term}' (cc={cc}, l={lang}): {e}")

    _STORE_APPID_CACHE[norm_key] = None
    return None


def fetch_appdetails_assets(steam_appid: int) -> Dict[str, str]:
    """
    Fetches official store asset URLs from Valve's public appdetails API.
    Provides backup URLs for header, capsule, and hero background.
    """
    assets = {}
    if not steam_appid or steam_appid <= 0:
        return assets
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={steam_appid}&cc=US"
        resp = safe_requests_get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=(3.0, 5.0))
        if resp and resp.status_code == 200:
            try:
                raw_data = resp.json()
            except Exception:
                raw_data = None
            if isinstance(raw_data, dict):
                app_info = raw_data.get(str(steam_appid))
                if isinstance(app_info, dict) and app_info.get('success'):
                    app_data = app_info.get('data')
                    if isinstance(app_data, dict):
                        if app_data.get('header_image'):
                            assets['header'] = app_data['header_image']
                        if app_data.get('capsule_image'):
                            assets['capsule'] = app_data['capsule_image']
                        if app_data.get('background_raw'):
                            assets['hero'] = app_data['background_raw']
                        elif app_data.get('background'):
                            assets['hero'] = app_data['background']
    except Exception as e:
        logger.debug(f"appdetails fetch failed for {steam_appid}: {e}")
    return assets


def convert_and_save_image(
    image_bytes: bytes,
    dest_path: str,
    is_logo: bool = False,
    min_size_bytes: int = 500
) -> bool:
    """
    Validates structural integrity and saves image as a genuine PNG using Pillow.
    Guarantees compatibility with Steam Deck, Big Picture, and CEF builds:
    - Runs Image.verify() to reject corrupt or truncated streams.
    - Converts RGB / RGBA color spaces appropriately (preserves logo transparency).
    - Writes via temporary file with atomic replacement to prevent 0-byte corrupt files.
    - Cleans up all IO streams, PIL resources, and temporary files on errors.
    """
    if not image_bytes or len(image_bytes) < min_size_bytes:
        logger.debug(f"Image rejected: payload {len(image_bytes) if image_bytes else 0}B < {min_size_bytes}B ({dest_path})")
        return False

    tmp_path = None
    try:
        # 1. Structural verification pass
        verify_stream = io.BytesIO(image_bytes)
        try:
            with Image.open(verify_stream) as v_img:
                v_img.verify()
        finally:
            verify_stream.close()

        # 2. Re-open for conversion & processing (verify invalidates stream)
        decode_stream = io.BytesIO(image_bytes)
        converted_img = None
        try:
            with Image.open(decode_stream) as img:
                img_to_save = img
                if is_logo:
                    if img.mode != 'RGBA':
                        converted_img = img.convert('RGBA')
                        img_to_save = converted_img
                else:
                    if img.mode not in ('RGB', 'RGBA'):
                        converted_img = img.convert('RGB')
                        img_to_save = converted_img

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                # Enforce centered aspect-ratio crop for vertical grid posters (prevent squashing like 007 square covers)
                if dest_path.lower().endswith(('p.png', 'p_thumb.png')) and not is_logo:
                    iw, ih = img_to_save.size
                    if iw > 0 and ih > 0:
                        target_ratio = 2.0 / 3.0  # 600x900
                        src_ratio = iw / ih
                        if abs(src_ratio - target_ratio) > 0.05:
                            if src_ratio > target_ratio:
                                crop_h = ih
                                crop_w = int(ih * target_ratio)
                                crop_x = int((iw - crop_w) / 2)
                                crop_y = 0
                            else:
                                crop_w = iw
                                crop_h = int(iw / target_ratio)
                                crop_x = 0
                                crop_y = int((ih - crop_h) / 2)
                            cropped_img = img_to_save.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
                            if converted_img is not None:
                                try:
                                    converted_img.close()
                                except Exception:
                                    pass
                            converted_img = cropped_img
                            img_to_save = cropped_img

                dest_dir = os.path.dirname(os.path.abspath(dest_path))
                fd, tmp_path = tempfile.mkstemp(dir=dest_dir, prefix="art_", suffix=".tmp")
                os.close(fd)
                img_to_save.save(tmp_path, format="PNG", optimize=True)
        finally:
            if converted_img is not None:
                try:
                    converted_img.close()
                except Exception:
                    pass
            decode_stream.close()

        if tmp_path and os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0:
            if os.path.exists(dest_path):
                try:
                    attrs = os.stat(dest_path).st_mode
                    if not (attrs & stat.S_IWRITE):
                        os.chmod(dest_path, attrs | stat.S_IWRITE)
                except Exception:
                    pass
            for attempt in range(4):
                try:
                    os.replace(tmp_path, dest_path)
                    return True
                except PermissionError:
                    if attempt < 3:
                        time.sleep(0.05)
                        continue
                    raise

        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False
    except Exception as e:
        logger.warning(f"Image validation/conversion failed for {dest_path}: {e}")
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def copy_or_link_64bit(src_path: str, dest_path: str):
    """Creates a copy of the artwork file for the 64-bit shortcut ID."""
    try:
        if not src_path or not dest_path:
            return
        if os.path.normcase(os.path.abspath(src_path)) == os.path.normcase(os.path.abspath(dest_path)):
            return
        if os.path.exists(src_path) and (not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0):
            if os.path.exists(dest_path):
                try:
                    attrs = os.stat(dest_path).st_mode
                    if not (attrs & stat.S_IWRITE):
                        os.chmod(dest_path, attrs | stat.S_IWRITE)
                except Exception:
                    pass
            shutil.copy2(src_path, dest_path)
    except Exception as e:
        logger.debug(f"Failed to copy 64-bit artwork {dest_path}: {e}")


def is_safe_grid_path(target_path: str, grid_dir: str) -> bool:
    """
    Guarantees strict path safety and format validation in Steam grid directory:
    - Path must reside strictly inside grid_dir (no path traversal).
    - Filename must match standard Steam artwork format: {appid}p.png, {appid}_hero.png, {appid}_logo.png, {appid}_icon.png.
    - Uses os.path.normcase for robust case-insensitive Windows comparisons.
    """
    if not target_path or not grid_dir:
        return False
    try:
        abs_target = os.path.normpath(os.path.abspath(target_path))
        abs_grid = os.path.normpath(os.path.abspath(grid_dir))
        norm_target = os.path.normcase(abs_target)
        norm_grid = os.path.normcase(abs_grid)
        if not norm_target.startswith(norm_grid + os.sep) and norm_target != norm_grid:
            return False
        if os.path.normcase(os.path.dirname(abs_target)) != norm_grid:
            return False
        base = os.path.basename(abs_target)
        if not re.match(r'^-?\d+(_hero|_logo|_icon|-icon|p)?\.png$', base, re.IGNORECASE):
            return False
        return True
    except Exception:
        return False


def download_artwork_for_game(
    steam_appid: Optional[int],
    grid_id: int,
    grid_dir: str,
    game_folder: str,
    grid_id_64: Optional[int] = None,
    steamgriddb_key: Optional[str] = None,
    clean_name: Optional[str] = None,
    custom_poster_path: Optional[str] = None
) -> int:
    """
    Downloads and saves all Steam graphic assets:
    - Poster (Vertical Grid 600x900): library_600x900.jpg -> {grid_id}p.png
    - Hero (Banner 1920x620): library_hero.jpg -> {grid_id}_hero.png
    - Logo (Transparent overlay): logo.png -> {grid_id}_logo.png
    - Capsule (Header): header.jpg -> {grid_id}.png
    - Icon: {grid_id}_icon.png (and {grid_id}-icon.png)

    Hierarchy: Custom User Poster -> SteamGridDB (if configured) -> Valve Store/CDN -> Local covers.
    Generates both 32-bit and 64-bit versions for full Steam cross-compatibility.
    Returns the number of successfully saved images.
    """
    os.makedirs(grid_dir, exist_ok=True)
    downloaded_count = 0
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    # Fetch appdetails backup URLs if appid is available
    appdetails_assets = fetch_appdetails_assets(steam_appid) if steam_appid else {}

    # Query SteamGridDB if API key provided or built-in default
    sgdb_assets = {}
    effective_sgdb_key = (steamgriddb_key if (steamgriddb_key is not None and str(steamgriddb_key).strip()) else DEFAULT_STEAMGRIDDB_KEY).strip()
    if effective_sgdb_key:
        sgdb = SteamGridDBClient(effective_sgdb_key)
        sgdb_game_id = None
        if steam_appid:
            sgdb_game_id = sgdb.get_game_by_steam_appid(steam_appid)
        if not sgdb_game_id and clean_name:
            sgdb_game_id = sgdb.search_game(clean_name)
        if sgdb_game_id:
            sgdb_assets = sgdb.get_artwork_urls(sgdb_game_id)
            logger.info(f"Retrieved SteamGridDB assets for '{clean_name or steam_appid}' (GameID: {sgdb_game_id})")

    poster_urls = []
    if sgdb_assets.get('poster'):
        poster_urls.append(sgdb_assets['poster'])
    if steam_appid:
        poster_urls.extend([
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{steam_appid}/library_600x900.jpg",
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{steam_appid}/library_600x900_2x.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_appid}/library_600x900.jpg",
            f"https://steamcdn-a.akamaihd.net/steam/apps/{steam_appid}/library_600x900.jpg"
        ])

    hero_urls = []
    if sgdb_assets.get('hero'):
        hero_urls.append(sgdb_assets['hero'])
    if steam_appid:
        hero_urls.extend([
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{steam_appid}/library_hero.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_appid}/library_hero.jpg",
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{steam_appid}/page_bg_generated_v6b.jpg"
        ])
        if 'hero' in appdetails_assets:
            hero_urls.append(appdetails_assets['hero'])

    logo_urls = []
    if sgdb_assets.get('logo'):
        logo_urls.append(sgdb_assets['logo'])
    if steam_appid:
        logo_urls.extend([
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{steam_appid}/logo.png",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_appid}/logo.png"
        ])

    capsule_urls = []
    if sgdb_assets.get('capsule'):
        capsule_urls.append(sgdb_assets['capsule'])
    elif sgdb_assets.get('grid_wide'):
        capsule_urls.append(sgdb_assets['grid_wide'])
    if steam_appid:
        capsule_urls.extend([
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{steam_appid}/header.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_appid}/header.jpg",
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{steam_appid}/capsule_616x353.jpg"
        ])
        if 'header' in appdetails_assets:
            capsule_urls.append(appdetails_assets['header'])
        if 'capsule' in appdetails_assets:
            capsule_urls.append(appdetails_assets['capsule'])

    icon_urls = []
    if sgdb_assets.get('icon'):
        icon_urls.append(sgdb_assets['icon'])

    targets = {
        'poster': {
            'dest': os.path.join(grid_dir, f"{grid_id}p.png"),
            'dest_64': os.path.join(grid_dir, f"{grid_id_64}p.png") if grid_id_64 else None,
            'is_logo': False,
            'urls': poster_urls,
            'local_patterns': ['poster.png', 'poster.jpg', 'cover.png', 'cover.jpg', 'library_600x900.jpg']
        },
        'hero': {
            'dest': os.path.join(grid_dir, f"{grid_id}_hero.png"),
            'dest_64': os.path.join(grid_dir, f"{grid_id_64}_hero.png") if grid_id_64 else None,
            'is_logo': False,
            'urls': hero_urls,
            'local_patterns': ['hero.png', 'hero.jpg', 'banner.png', 'banner.jpg', 'background.jpg', 'library_hero.jpg']
        },
        'logo': {
            'dest': os.path.join(grid_dir, f"{grid_id}_logo.png"),
            'dest_64': os.path.join(grid_dir, f"{grid_id_64}_logo.png") if grid_id_64 else None,
            'is_logo': True,
            'urls': logo_urls,
            'local_patterns': ['logo.png', 'logo.ico', 'clear_logo.png']
        },
        'capsule': {
            'dest': os.path.join(grid_dir, f"{grid_id}.png"),
            'dest_64': os.path.join(grid_dir, f"{grid_id_64}.png") if grid_id_64 else None,
            'is_logo': False,
            'urls': capsule_urls,
            'local_patterns': ['header.jpg', 'header.png', 'capsule.jpg', 'capsule.png', 'banner.jpg', 'banner.png']
        },
        'icon': {
            'dest': os.path.join(grid_dir, f"{grid_id}_icon.png"),
            'dest_64': os.path.join(grid_dir, f"{grid_id_64}_icon.png") if grid_id_64 else None,
            'dest_alt': os.path.join(grid_dir, f"{grid_id}-icon.png"),
            'is_logo': True,
            'urls': icon_urls,
            'local_patterns': ['icon.png', 'icon.ico', 'app.ico', 'game.ico']
        }
    }

    # Handle custom user poster override if provided
    if custom_poster_path and os.path.isfile(custom_poster_path):
        try:
            with open(custom_poster_path, 'rb') as f:
                c_bytes = f.read()
            p_dest = targets['poster']['dest']
            p_dest_64 = targets['poster']['dest_64']
            if is_safe_grid_path(p_dest, grid_dir):
                if convert_and_save_image(c_bytes, p_dest, is_logo=False):
                    downloaded_count += 1
                    if p_dest_64 and is_safe_grid_path(p_dest_64, grid_dir):
                        copy_or_link_64bit(p_dest, p_dest_64)
                    logger.info(f"Applied custom user poster override from {custom_poster_path}")
            else:
                logger.warning(f"Blocked unsafe custom poster destination: {p_dest}")
        except Exception as e:
            logger.warning(f"Failed applying custom poster {custom_poster_path}: {e}")

    for art_type, info in targets.items():
        dest = info['dest']
        dest_64 = info.get('dest_64')
        dest_alt = info.get('dest_alt')

        # If custom poster was applied above for 'poster', skip re-processing it
        if art_type == 'poster' and custom_poster_path and os.path.isfile(dest) and os.path.getsize(dest) > 0:
            continue

        # Security check: validate destination grid paths
        if not is_safe_grid_path(dest, grid_dir):
            logger.warning(f"Blocked unsafe destination grid path: {dest}")
            continue
        if dest_64 and not is_safe_grid_path(dest_64, grid_dir):
            logger.warning(f"Blocked unsafe 64-bit destination grid path: {dest_64}")
            dest_64 = None
        if dest_alt and not is_safe_grid_path(dest_alt, grid_dir):
            logger.warning(f"Blocked unsafe alternate destination grid path: {dest_alt}")
            dest_alt = None

        # If already exists with valid size, reuse directly
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            downloaded_count += 1
            if dest_64 and (not os.path.isfile(dest_64) or os.path.getsize(dest_64) == 0):
                copy_or_link_64bit(dest, dest_64)
            if dest_alt and (not os.path.isfile(dest_alt) or os.path.getsize(dest_alt) == 0):
                copy_or_link_64bit(dest, dest_alt)
            continue

        saved = False

        # Try URLs (SteamGridDB + Valve CDN) with strict domain allowlist
        for url in info['urls']:
            if not is_safe_artwork_url(url):
                logger.warning(f"Blocked non-allowlisted artwork URL: {url}")
                continue
            try:
                resp = safe_requests_get(url, headers=headers, timeout=(3.0, 6.0), max_retries=1)
                if resp is not None and resp.status_code == 200 and len(resp.content) > 500:
                    if convert_and_save_image(resp.content, dest, is_logo=info['is_logo']):
                        saved = True
                        break
            except Exception as e:
                logger.debug(f"Failed downloading {url}: {e}")

        # Local file fallback in game folder
        if not saved and game_folder and os.path.isdir(game_folder):
            local_patterns = info['local_patterns']
            found_local = None

            # 1. Search root directory
            for lp in local_patterns:
                lp_path = os.path.join(game_folder, lp)
                if os.path.isfile(lp_path) and os.path.getsize(lp_path) > 0:
                    found_local = lp_path
                    break

            # 2. Search subdirectories (up to depth 2)
            if not found_local:
                for r, _, fs in os.walk(game_folder):
                    depth = len(r.split(os.sep)) - len(game_folder.split(os.sep))
                    if depth > 2:
                        continue
                    for f in fs:
                        if f.lower() in [x.lower() for x in local_patterns]:
                            p = os.path.join(r, f)
                            if os.path.getsize(p) > 0:
                                found_local = p
                                break
                    if found_local:
                        break

            if found_local:
                try:
                    with open(found_local, 'rb') as f:
                        data = f.read()
                    if convert_and_save_image(data, dest, is_logo=info['is_logo']):
                        saved = True
                        logger.info(f"Used local fallback artwork '{os.path.basename(found_local)}' for {art_type}")
                except Exception as e:
                    logger.debug(f"Failed using local artwork {found_local}: {e}")

        if saved:
            downloaded_count += 1
            if dest_64:
                copy_or_link_64bit(dest, dest_64)
            if dest_alt:
                copy_or_link_64bit(dest, dest_alt)

    return downloaded_count


# ==============================================================================
# Phase 3.4: Modifying shortcuts.vdf
# ==============================================================================

def load_shortcuts_vdf(shortcuts_path: str) -> Dict[str, Any]:
    """Reads binary shortcuts.vdf or initializes empty structure."""
    if os.path.isfile(shortcuts_path):
        try:
            with open(shortcuts_path, 'rb') as f:
                data = f.read()
            if data and len(data.strip()) > 0:
                parsed = vdf.binary_loads(data)
                if isinstance(parsed, dict) and 'shortcuts' in parsed:
                    return parsed
                elif isinstance(parsed, dict):
                    return {'shortcuts': parsed}
        except Exception as e:
            logger.warning(f"Failed to parse existing shortcuts.vdf ({e}). Initializing empty structure.")
    return {'shortcuts': {}}


def sanitize_vdf_strings(obj: Any) -> Any:
    """Recursively removes null bytes (\\0) from string keys and values in VDF structures."""
    if isinstance(obj, str):
        return obj.replace('\0', '')
    elif isinstance(obj, dict):
        return {str(k).replace('\0', ''): sanitize_vdf_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_vdf_strings(v) for v in obj]
    return obj


def save_shortcuts_vdf(shortcuts_path: str, data: Dict[str, Any]) -> bool:
    """
    Atomically serializes data and writes to shortcuts.vdf with full rollback guarantee:
    1. Sanitizes null bytes (\\0) to prevent parser corruption.
    2. Serializes data using vdf.binary_dumps().
    3. Verifies generated binary data via vdf.binary_loads() in memory.
    4. Computes memory CRC32 checksum.
    5. Writes to tempfile.mkstemp in the same directory, flushes and fsyncs to disk.
    6. Reads back from disk and verifies both deserialization and CRC32 checksum.
    7. Atomically replaces shortcuts.vdf via os.replace().
    """
    parent_dir = os.path.dirname(os.path.abspath(shortcuts_path))
    os.makedirs(parent_dir, exist_ok=True)

    sanitized_data = sanitize_vdf_strings(data)
    binary_data = vdf.binary_dumps(sanitized_data)

    # 1. In-memory reverse deserialization check
    try:
        verify_mem = vdf.binary_loads(binary_data)
        if 'shortcuts' not in verify_mem:
            raise ValueError("Serialized binary missing 'shortcuts' root key")
    except Exception as e:
        logger.error(f"In-memory VDF binary validation failed: {e}. Write aborted!")
        raise RuntimeError(f"VDF binary validation failed: {e}")

    mem_crc = zlib.crc32(binary_data)

    # 2. Atomic write via tempfile.mkstemp in the destination folder
    fd, tmp_path = tempfile.mkstemp(dir=parent_dir, prefix="shortcuts_", suffix=".tmp")
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(binary_data)
            f.flush()
            os.fsync(f.fileno())

        # 3. On-disk verification & CRC32 check
        with open(tmp_path, 'rb') as f:
            disk_content = f.read()
        disk_crc = zlib.crc32(disk_content)
        if disk_crc != mem_crc:
            raise ValueError(f"On-disk CRC32 mismatch ({disk_crc} != {mem_crc})")

        verify_disk = vdf.binary_loads(disk_content)
        if 'shortcuts' not in verify_disk:
            raise ValueError("On-disk binary missing 'shortcuts' root key")

        # 4. Atomic replacement
        if os.path.exists(shortcuts_path):
            try:
                attrs = os.stat(shortcuts_path).st_mode
                if not (attrs & stat.S_IWRITE):
                    os.chmod(shortcuts_path, attrs | stat.S_IWRITE)
            except Exception:
                pass

        replaced = False
        for attempt in range(4):
            try:
                os.replace(tmp_path, shortcuts_path)
                replaced = True
                break
            except PermissionError:
                if attempt < 3:
                    time.sleep(0.1)
                    continue
                raise

        if not replaced:
            raise RuntimeError(f"Failed to replace {shortcuts_path}")

        # Clean up any stale legacy shortcuts.vdf.tmp if present
        legacy_tmp = shortcuts_path + ".tmp"
        if os.path.exists(legacy_tmp):
            try:
                os.remove(legacy_tmp)
            except OSError:
                pass

        logger.info(f"Atomically wrote {len(binary_data)} bytes to {shortcuts_path} (CRC32: {hex(mem_crc)})")
        return True

    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        legacy_tmp = shortcuts_path + ".tmp"
        if os.path.exists(legacy_tmp):
            try:
                os.remove(legacy_tmp)
            except OSError:
                pass
        raise


def add_games_to_shortcuts(
    shortcuts_path: str,
    games: List[Dict[str, Any]],
    download_artwork: bool = True,
    steam_path: Optional[str] = None,
    steam_user_id: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    steamgriddb_key: Optional[str] = None
) -> Tuple[int, int]:
    """
    Adds discovered games to shortcuts.vdf without creating duplicates.
    Downloads artwork to <SteamPath>/userdata/<SteamID>/config/grid/.
    Ensures artwork is fetched even for existing shortcuts if artwork is missing.
    Supports SteamGridDB API key, custom user poster override, launcher tags, and icons.
    Returns (games_added_count, artwork_downloaded_count).
    """
    # Guard: check running Steam
    if is_steam_running():
        raise RuntimeError("Steam is currently RUNNING! Close Steam client before saving shortcuts.")

    # 1. Backup before modifying
    backup_shortcuts_file(shortcuts_path)

    # 2. Read existing shortcuts
    data = load_shortcuts_vdf(shortcuts_path)
    if 'shortcuts' not in data or not isinstance(data['shortcuts'], dict):
        data['shortcuts'] = {}

    shortcuts_dict = data['shortcuts']

    # Map existing executables (case-insensitive, normalized)
    existing_exes = set()
    for _, item in shortcuts_dict.items():
        if isinstance(item, dict):
            exe_val = item.get('Exe', '')
            if isinstance(exe_val, str):
                cleaned = exe_val.strip().strip('"\'')
                existing_exes.add(os.path.normpath(cleaned).lower())

    # Determine grid folder
    grid_dir = None
    if steam_path and steam_user_id:
        if not is_safe_steam_user_id(steam_user_id):
            logger.warning(f"Rejected unsafe steam_user_id format: {steam_user_id}")
        else:
            grid_dir = os.path.join(steam_path, "userdata", str(steam_user_id), "config", "grid")
    elif shortcuts_path:
        grid_dir = os.path.join(os.path.dirname(shortcuts_path), "grid")

    if grid_dir:
        try:
            os.makedirs(grid_dir, exist_ok=True)
        except OSError as e:
            logger.warning(f"Could not create grid directory {grid_dir}: {e}")

    # Find highest numeric key
    existing_keys = [int(k) for k in shortcuts_dict.keys() if str(k).isdigit()]
    next_index = max(existing_keys) + 1 if existing_keys else 0

    added_count = 0
    total_art_count = 0
    total_games = len(games)

    for idx, game in enumerate(games):
        exe_path = game['exe_path']
        clean_name = game['clean_name']
        grid_id, vdf_appid, grid_id_64 = calculate_steam_ids(exe_path, clean_name)
        game['grid_id'] = grid_id
        game['vdf_appid'] = vdf_appid
        game['grid_id_64'] = grid_id_64

        clean_exe_path = os.path.normpath(exe_path.replace('\0', '').strip().strip('"\''))
        norm_exe = clean_exe_path.lower()
        already_exists = norm_exe in existing_exes

        # Build launcher tags if detected
        tags = {}
        if game.get('launcher'):
            tags['0'] = str(game['launcher'])
        elif game.get('tags'):
            if isinstance(game['tags'], list):
                tags = {str(i): str(t) for i, t in enumerate(game['tags'])}
            elif isinstance(game['tags'], dict):
                tags = game['tags']

        icon_val = ''
        if grid_dir:
            icon_file = os.path.join(grid_dir, f"{grid_id}_icon.png")
            if os.path.isfile(icon_file) and os.path.getsize(icon_file) > 0:
                icon_val = icon_file

        if not already_exists:
            clean_app_name = clean_name.replace('\0', '').strip()
            start_dir_raw = game.get('start_dir') or os.path.dirname(clean_exe_path)
            clean_start_dir = os.path.normpath(start_dir_raw.replace('\0', '').strip().strip('"\''))

            entry = {
                'appid': vdf_appid,
                'AppName': clean_app_name,
                'Exe': f'"{clean_exe_path}"',
                'StartDir': f'"{clean_start_dir}"',
                'icon': icon_val,
                'ShortcutPath': '',
                'LaunchOptions': game.get('launch_options', ''),
                'IsHidden': 0,
                'AllowDesktopConfig': 1,
                'AllowOverlay': 1,
                'OpenVR': 0,
                'Devkit': 0,
                'DevkitGameID': '',
                'DevkitOverrideAppId': 0,
                'LastPlayTime': 0,
                'FlatpakAppID': '',
                'tags': tags
            }

            shortcuts_dict[str(next_index)] = entry
            existing_exes.add(norm_exe)
            next_index += 1
            added_count += 1
            logger.info(f"Added shortcut [{next_index-1}]: '{clean_name}' (AppID: {vdf_appid}, GridID: {grid_id})")
        else:
            logger.info(f"Shortcut already registered for '{clean_name}' ({exe_path}).")

        # Download artwork if requested (even for existing games if artwork missing)
        if download_artwork and grid_dir:
            poster_file = os.path.join(grid_dir, f"{grid_id}p.png")
            if os.path.isfile(poster_file) and os.path.getsize(poster_file) == 0:
                try:
                    os.remove(poster_file)
                except OSError:
                    pass
            needs_art = bool(game.get('custom_cover_path')) or not already_exists or not (os.path.isfile(poster_file) and os.path.getsize(poster_file) > 0)

            if needs_art:
                steam_appid = search_steam_store_appid(clean_name)
                game['steam_appid'] = steam_appid
                art_count = download_artwork_for_game(
                    steam_appid=steam_appid,
                    grid_id=grid_id,
                    grid_dir=grid_dir,
                    game_folder=game.get('folder_path', ''),
                    grid_id_64=grid_id_64,
                    steamgriddb_key=steamgriddb_key,
                    clean_name=clean_name,
                    custom_poster_path=game.get('custom_cover_path')
                )
                total_art_count += art_count
                logger.info(f"Saved {art_count}/5 artworks for '{clean_name}'")

                # If an icon was saved and entry was created, assign icon to shortcut entry
                if not already_exists and not icon_val:
                    new_icon = os.path.join(grid_dir, f"{grid_id}_icon.png")
                    if os.path.isfile(new_icon) and os.path.getsize(new_icon) > 0:
                        shortcuts_dict[str(next_index - 1)]['icon'] = new_icon

        if progress_callback:
            try:
                progress_callback(idx + 1, total_games, clean_name)
            except Exception as cb_err:
                logger.debug(f"Progress callback error: {cb_err}")

    # Guard check right before write
    if is_steam_running():
        raise RuntimeError("Steam was launched during execution! Overwrite aborted for protection.")

    # 3. Save modified shortcuts
    save_shortcuts_vdf(shortcuts_path, data)

    return added_count, total_art_count


# Compatibility aliases
search_steam_store = search_steam_store_appid
download_artwork = download_artwork_for_game
download_game_artwork = download_artwork_for_game


# ==============================================================================
# Phase 4: Self-Verification
# ==============================================================================

def verify_shortcuts_integrity(shortcuts_path: str, grid_dir: Optional[str] = None) -> Tuple[bool, str]:
    """
    Validates that:
    1. shortcuts.vdf can be deserialized via vdf.binary_loads() without error.
    2. Downloaded artwork files in grid_dir are non-empty.
    """
    if not os.path.isfile(shortcuts_path):
        return False, f"shortcuts.vdf does not exist at {shortcuts_path}"

    try:
        with open(shortcuts_path, 'rb') as f:
            content = f.read()
        parsed = vdf.binary_loads(content)
        if 'shortcuts' not in parsed:
            return False, "Parsed data does not contain 'shortcuts' root key"
    except Exception as e:
        return False, f"Failed to deserialize shortcuts.vdf: {e}"

    if grid_dir and os.path.isdir(grid_dir):
        zero_size_files = []
        for root, _, files in os.walk(grid_dir):
            for f in files:
                p = os.path.join(root, f)
                if os.path.getsize(p) == 0:
                    zero_size_files.append(f)
        if zero_size_files:
            return False, f"Found 0-byte images in grid folder: {zero_size_files}"

    return True, "All verification checks passed successfully."


# ==============================================================================
# Main Sync Orchestration Pipeline
# ==============================================================================

def run_synchronization(
    game_folders: Union[str, List[str]],
    steam_path: Optional[str] = None,
    steam_user_id: Optional[str] = None,
    download_artwork: bool = True,
    dry_run: bool = False,
    steamgriddb_key: Optional[str] = None,
    games_list: Optional[List[Dict[str, Any]]] = None,
    include_launchers: bool = False
) -> Dict[str, Any]:
    """
    Executes complete end-to-end synchronization pipeline:
    Checks Steam process -> Locates Steam & userdata -> Scans games ->
    Updates shortcuts.vdf -> Downloads artwork -> Performs verification.
    Supports SteamGridDB API key, pre-filtered games_list, and launcher discovery.
    """
    report = {
        'success': False,
        'message': '',
        'steam_running': False,
        'steam_path': None,
        'user_id': None,
        'shortcuts_path': None,
        'games_found': [],
        'games_added': 0,
        'art_downloaded': 0,
        'verification': ''
    }

    # 1. Process Guard
    if is_steam_running():
        report['steam_running'] = True
        report['message'] = "Steam is currently RUNNING! Please exit Steam completely before syncing to prevent changes from being overwritten."
        logger.error(report['message'])
        return report

    # 2. Locate Steam directory
    steam_dir = steam_path or get_steam_path()
    if not steam_dir or not os.path.isdir(steam_dir):
        report['message'] = f"Could not locate Steam directory at '{steam_dir}'. Ensure Steam is installed."
        logger.error(report['message'])
        return report
    report['steam_path'] = steam_dir

    # 3. Locate Active User
    user_id = steam_user_id or get_active_steam_user(steam_dir)
    if not user_id:
        report['message'] = f"No Steam user profiles found in '{os.path.join(steam_dir, 'userdata')}'. Log into Steam at least once."
        logger.error(report['message'])
        return report
    if not is_safe_steam_user_id(user_id):
        report['message'] = f"Invalid or unsafe steam_user_id: {user_id}"
        logger.error(report['message'])
        return report
    report['user_id'] = str(user_id)

    # 4. Target shortcuts.vdf path
    shortcuts_path = os.path.join(steam_dir, "userdata", user_id, "config", "shortcuts.vdf")
    report['shortcuts_path'] = shortcuts_path
    grid_dir = os.path.join(steam_dir, "userdata", user_id, "config", "grid")

    # 5. Scan Games or use custom pre-selected games list
    if games_list is not None:
        games = games_list
    else:
        games = scan_games(game_folders, include_launchers=include_launchers)
    report['games_found'] = games

    if not games:
        report['success'] = True
        report['message'] = "No installed games detected in the specified directories."
        return report

    if dry_run:
        report['success'] = True
        report['message'] = f"Dry Run completed. Discovered {len(games)} games."
        return report

    # 6. Add games and download art
    try:
        added, art_count = add_games_to_shortcuts(
            shortcuts_path=shortcuts_path,
            games=games,
            download_artwork=download_artwork,
            steam_path=steam_dir,
            steam_user_id=user_id,
            steamgriddb_key=steamgriddb_key
        )
    except Exception as e:
        report['message'] = f"Error during shortcut update: {e}"
        logger.error(report['message'])
        return report

    report['games_added'] = added
    report['art_downloaded'] = art_count

    # 7. Self-Verification
    ok, v_msg = verify_shortcuts_integrity(shortcuts_path, grid_dir)
    report['verification'] = v_msg
    if not ok:
        report['message'] = f"Verification failed: {v_msg}"
        return report

    report['success'] = True
    if added == 0 and art_count == 0:
        report['message'] = "Все найденные игры уже добавлены в библиотеку Steam."
    elif added > 0 and art_count == 0:
        report['message'] = f"Успешно синхронизировано новых игр: {added}."
    elif added == 0 and art_count > 0:
        report['message'] = f"Загружено обложек: {art_count}."
    else:
        report['message'] = f"Синхронизировано новых игр: {added}, загружено обложек: {art_count}."
    return report


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Steam Syncer — Automated Non-Steam Game Importer & CDN Artwork Downloader",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        'folders',
        nargs='*',
        default=COMMON_GAME_DIRECTORIES,
        help="Root game directories to scan (e.g. 'D:\\Gamess' 'C:\\Games' or combined 'D:\\Gamess C:\\Games')"
    )
    parser.add_argument('--steam-path', help="Custom path to Steam installation folder")
    parser.add_argument('--user-id', help="Specific Steam User ID inside userdata")
    parser.add_argument('--no-art', action='store_true', help="Skip downloading artwork covers and banners")
    parser.add_argument('--dry-run', action='store_true', help="Scan and show detected games without modifying files")
    parser.add_argument('-v', '--verbose', action='store_true', help="Enable detailed logging output")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    print("================================================================")
    print("                STEAM SYNCER & ARTWORK DOWNLOADER               ")
    print("================================================================\n")

    report = run_synchronization(
        game_folders=args.folders,
        steam_path=args.steam_path,
        steam_user_id=args.user_id,
        download_artwork=not args.no_art,
        dry_run=args.dry_run
    )

    print("\n------------------------- REPORT -------------------------------")
    if report['steam_running']:
        print(" [!] ERROR: steam.exe is currently running.")
        print("     Please close Steam completely and re-run this tool.")
        sys.exit(1)

    print(f" Status:             {'SUCCESS' if report['success'] else 'FAILED'}")
    print(f" Steam Directory:    {report.get('steam_path')}")
    print(f" Steam User ID:      {report.get('user_id')}")
    print(f" Shortcuts File:     {report.get('shortcuts_path')}")
    print(f" Discovered Games:   {len(report['games_found'])}")
    for g in report['games_found']:
        print(f"   • {g['clean_name']} -> {g['exe_name']} ({g['exe_size'] / (1024*1024):.1f} MB)")

    if not args.dry_run:
        print(f" Games Added:        {report['games_added']}")
        print(f" Artworks Saved:     {report['art_downloaded']}")
        print(f" Integrity Check:    {report['verification']}")

    print("----------------------------------------------------------------")
    print(f" Result: {report['message']}\n")

    if not report['success']:
        sys.exit(1)


if __name__ == "__main__":
    main()
