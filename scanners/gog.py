#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GOG Galaxy Scanner (scanners/gog.py)
Scans GOG Galaxy installed games from Windows Registry:
- HKLM\\SOFTWARE\\WOW6432Node\\GOG.com\\Games\\*
- HKLM\\SOFTWARE\\GOG.com\\Games\\*
- HKCU\\SOFTWARE\\GOG.com\\Games\\*
Extracts PATH, EXE, GAMENAME, and gameID.
"""

import os
import logging
from typing import List, Dict, Any, Optional

from scanners.discovered_game import DiscoveredGame

logger = logging.getLogger("SteamSyncer.GOGScanner")


def scan_gog_games() -> List[DiscoveredGame]:
    """
    Scans GOG Galaxy installed games from Windows Registry:
    - HKLM\\SOFTWARE\\WOW6432Node\\GOG.com\\Games\\*
    - HKLM\\SOFTWARE\\GOG.com\\Games\\*
    - HKCU\\SOFTWARE\\GOG.com\\Games\\*
    Extracts PATH, EXE, GAMENAME, and gameID.
    Applies junk filter on unins000.exe and crash report binaries.
    """
    games: List[DiscoveredGame] = []
    seen_paths = set()

    try:
        import winreg
    except ImportError:
        return []

    from steam_syncer import clean_game_name, find_best_game_exe, is_valid_executable

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


# Backwards compatibility alias
scan_gog_galaxy_games = scan_gog_games
