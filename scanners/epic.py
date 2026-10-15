#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Epic Games Store Scanner (scanners/epic.py)
Parses Epic Games Launcher manifests (*.item) to detect installed games.
Extracts DisplayName, InstallLocation, LaunchExecutable, AppName.
Strictly filters out Epic Games Launcher client and helper binaries.
"""

import os
import glob
import json
import logging
from typing import List, Dict, Any, Optional

from scanners.discovered_game import DiscoveredGame

logger = logging.getLogger("SteamSyncer.EpicScanner")

# Exact names and substrings identifying the Epic Games Launcher itself or system tools
EPIC_LAUNCHER_APP_NAMES = {
    'launcher', 'epicgameslauncher', 'eos', 'epicgames', 'epicgamesstore', 'epiconlineservices'
}

EPIC_LAUNCHER_PREFIXES = (
    'ue_', 'unrealengine', 'launcher', 'epicgameslauncher', 'epic_games', 'eos'
)

EPIC_LAUNCHER_DISPLAY_NAMES = [
    'epic games launcher', 'epic games', 'epic launcher', 'epic online services',
    'unreal engine', 'prerequisites', 'epic games store', 'eos'
]

EPIC_LAUNCHER_BINARIES = [
    'epicgameslauncher', 'epicgamesupdater', 'unrealenginelauncher',
    'epiconlineservices', 'epicwebhelper', 'eosbootstrapper', 'eosoverlayrenderer'
]


def scan_epic_games(manifest_dir: Optional[str] = None) -> List[DiscoveredGame]:
    """
    Parses Epic Games Launcher manifests (*.item) to detect installed games.
    Default directory: C:\\ProgramData\\Epic\\EpicGamesLauncher\\Data\\Manifests\\*.item
    Extracts DisplayName, InstallLocation, LaunchExecutable.
    Strictly filters out the Epic Games Launcher client, EOS, and non-game manifests.
    """
    if manifest_dir is None:
        manifest_dir = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"

    if not os.path.isdir(manifest_dir):
        return []

    from steam_syncer import clean_game_name, find_best_game_exe, is_valid_executable

    games: List[DiscoveredGame] = []
    seen_paths = set()

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

        if app_name_lower in EPIC_LAUNCHER_APP_NAMES or app_name_lower.startswith(EPIC_LAUNCHER_PREFIXES):
            continue
        if any(ign in disp_lower for ign in EPIC_LAUNCHER_DISPLAY_NAMES):
            continue
        if any(ign in launch_lower for ign in EPIC_LAUNCHER_BINARIES):
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

        # Secondary check: verify executable binary is valid and not a launcher helper
        exe_basename = os.path.basename(exe_path).lower()
        if exe_basename in {
            'epicgameslauncher.exe', 'epicgamesupdater.exe', 'unrealenginelauncher.exe',
            'eosbootstrapper.exe', 'epicwebhelper.exe', 'crashreportclient.exe'
        }:
            continue

        if not is_valid_executable(exe_basename, clean_name=clean_name):
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


# Backwards compatibility alias
scan_epic_games_manifests = scan_epic_games
