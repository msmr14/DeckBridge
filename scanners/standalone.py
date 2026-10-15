#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone / Custom Folders Scanner (scanners/standalone.py)
Scans custom folders, repacks, and drive directories (e.g. C:\\Games, D:\\Games).
Discovers root game executables with strict junk filtering:
unins000.exe, UnityCrashHandler*.exe, DXSETUP.exe, vcredist*.exe, CrashReport*.exe.
"""

import os
import logging
from typing import List, Dict, Any, Union, Optional

from scanners.discovered_game import DiscoveredGame

logger = logging.getLogger("SteamSyncer.StandaloneScanner")


def scan_standalone_games(
    root_directories: Union[str, List[str]],
    include_launchers: bool = False
) -> List[DiscoveredGame]:
    """
    Scans custom folders, repacks, and drive directories (e.g. C:\\Games, D:\\Games).
    Discovers root game executables with strict junk filtering:
    unins000.exe, UnityCrashHandler*.exe, DXSETUP.exe, vcredist*.exe, CrashReport*.exe.
    Optionally merges games discovered from Epic Games and GOG Galaxy.
    """
    from steam_syncer import (
        parse_folder_list,
        clean_game_name,
        find_best_game_exe,
        is_valid_executable,
        IGNORE_SUBFOLDERS,
        IGNORE_ROOT_NAMES
    )

    parsed_roots = parse_folder_list(root_directories)
    discovered_games: List[DiscoveredGame] = []
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
        # Strictly ignore folders whose name matches known root/launcher directories (e.g. Epic Games, GOG Games)
        norm_root_case = os.path.normcase(norm_root)
        root_prefix = norm_root_case if norm_root_case.endswith(os.sep) else norm_root_case + os.sep
        if not any(
            os.path.normcase(g['folder_path']) == norm_root_case or
            os.path.normcase(g['folder_path']).startswith(root_prefix)
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
            from scanners.epic import scan_epic_games
            epic_games = scan_epic_games()
            for eg in epic_games:
                norm_exe = os.path.normpath(eg['exe_path']).lower()
                if norm_exe not in seen_paths:
                    seen_paths.add(norm_exe)
                    discovered_games.append(eg)
        except Exception as e:
            logger.debug(f"Epic Games scan error: {e}")

        try:
            from scanners.gog import scan_gog_games
            gog_games = scan_gog_games()
            for gg in gog_games:
                norm_exe = os.path.normpath(gg['exe_path']).lower()
                if norm_exe not in seen_paths:
                    seen_paths.add(norm_exe)
                    discovered_games.append(gg)
        except Exception as e:
            logger.debug(f"GOG Galaxy scan error: {e}")

    return discovered_games


# Convenience alias matching legacy API
scan_games = scan_standalone_games


def scan_all_games(root_directories: Union[str, List[str]], include_launchers: bool = True) -> List[DiscoveredGame]:
    """Convenience wrapper for scanning both folder directories and installed launchers."""
    return scan_standalone_games(root_directories, include_launchers=include_launchers)
