#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safe shortcuts.vdf binary generator (steam_vdf.py)
Reads and writes Valve binary VDF shortcuts with rotating backups,
generates standard Steam shortcut fields, and computes 32-bit AppIDs.
"""

from typing import Dict, List, Tuple, Any, Optional, Union
import os
import zlib
import ctypes
import vdf
from steam_syncer import (
    backup_shortcuts_file,
    load_shortcuts_vdf,
    save_shortcuts_vdf,
    calculate_steam_ids,
    add_games_to_shortcuts,
    verify_shortcuts_integrity,
    clean_game_name,
    sanitize_vdf_strings
)

# Aliases matching Stage 3 specification
backup_shortcuts = backup_shortcuts_file
add_shortcuts = add_games_to_shortcuts


def load_shortcuts(shortcuts_path: Union[str, Any]) -> Dict[str, Any]:
    """
    Reads binary shortcuts.vdf file or open stream using vdf.binary_load / binary_loads.
    Returns dictionary with 'shortcuts' root key.
    """
    if hasattr(shortcuts_path, 'read'):
        try:
            parsed = vdf.binary_load(shortcuts_path)
            if isinstance(parsed, dict) and 'shortcuts' in parsed:
                return parsed
            elif isinstance(parsed, dict):
                return {'shortcuts': parsed}
        except Exception:
            return {'shortcuts': {}}
    return load_shortcuts_vdf(str(shortcuts_path))


def save_shortcuts(shortcuts_path: Union[str, Any], data: Dict[str, Any]) -> bool:
    """
    Atomically serializes data and writes to binary shortcuts.vdf using vdf.binary_dump / binary_dumps.
    """
    if hasattr(shortcuts_path, 'write'):
        sanitized = sanitize_vdf_strings(data)
        vdf.binary_dump(sanitized, shortcuts_path)
        return True
    return save_shortcuts_vdf(str(shortcuts_path), data)


def calculate_appid(exe_path: str, appname: str) -> int:
    """
    Calculates 32-bit signed integer appid for shortcuts.vdf:
    crc = zlib.crc32(f'"{exe}"{appname}'.encode('utf-8')) | 0x80000000
    Returns signed 32-bit integer.
    """
    _, vdf_appid, _ = calculate_steam_ids(exe_path, appname)
    return vdf_appid


class ShortcutEntry(dict):
    """
    Shortcut entry supporting both standard Valve PascalCase and task-specified lowercase keys.
    """
    KEY_MAP = {
        'appname': 'AppName',
        'exe': 'Exe',
        'startdir': 'StartDir',
        'launchoptions': 'LaunchOptions',
        'ishidden': 'IsHidden',
        'allowdesktopconfig': 'AllowDesktopConfig',
        'allowoverlay': 'AllowOverlay',
        'openvr': 'OpenVR',
        'appid': 'appid'
    }

    def __getitem__(self, item: str) -> Any:
        lower = str(item).lower()
        if lower in self.KEY_MAP and self.KEY_MAP[lower] in self:
            return super().__getitem__(self.KEY_MAP[lower])
        return super().__getitem__(item)

    def __contains__(self, item: object) -> bool:
        lower = str(item).lower()
        if lower in self.KEY_MAP and super().__contains__(self.KEY_MAP[lower]):
            return True
        return super().__contains__(item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            return self[item]
        except KeyError:
            return default


def generate_shortcut_entry(
    game: Dict[str, Any],
    next_index: int = 0
) -> ShortcutEntry:
    """
    Generates standard representation of a single shortcut entry for shortcuts.vdf:
    - appid (int32)
    - AppName / appname (str)
    - Exe / exe ("<path>")
    - StartDir / startdir ("<dir>")
    - LaunchOptions / launchoptions ("")
    - IsHidden = 0
    - AllowDesktopConfig = 1
    - AllowOverlay = 1
    - OpenVR = 0
    """
    exe_path = str(game.get('exe_path', '')).replace('\0', '').strip().strip('"\'')
    raw_name = str(game.get('clean_name') or game.get('name') or os.path.splitext(os.path.basename(exe_path))[0]).strip()
    appname = clean_game_name(raw_name)
    start_dir = str(game.get('start_dir') or game.get('folder_path') or os.path.dirname(exe_path)).replace('\0', '').strip().strip('"\'')

    grid_id, vdf_appid, _ = calculate_steam_ids(exe_path, appname)

    tags = {}
    if game.get('launcher'):
        tags['0'] = str(game['launcher'])
    elif game.get('source'):
        tags['0'] = str(game['source'])
    elif game.get('tags'):
        raw_tags = game['tags']
        if isinstance(raw_tags, dict):
            tags = raw_tags
        elif isinstance(raw_tags, (list, tuple, set)):
            tags = {str(i): str(t) for i, t in enumerate(raw_tags)}

    data = {
        'appid': vdf_appid,
        'AppName': appname,
        'Exe': f'"{exe_path}"',
        'StartDir': f'"{start_dir}"',
        'icon': str(game.get('icon', '')),
        'ShortcutPath': '',
        'LaunchOptions': str(game.get('launch_options', '')),
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
    return ShortcutEntry(data)


__all__ = [
    "backup_shortcuts",
    "backup_shortcuts_file",
    "load_shortcuts",
    "load_shortcuts_vdf",
    "save_shortcuts",
    "save_shortcuts_vdf",
    "calculate_steam_ids",
    "calculate_appid",
    "generate_shortcut_entry",
    "ShortcutEntry",
    "add_shortcuts",
    "add_games_to_shortcuts",
    "verify_shortcuts_integrity",
    "sanitize_vdf_strings"
]
