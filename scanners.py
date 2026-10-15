#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scanners Module — Auto-detectors for Epic Games Store, GOG Galaxy, and Standalone games.
Returns unified DiscoveredGame(name, exe_path, start_dir, source) objects.
"""

from scanners import (
    DiscoveredGame,
    scan_epic_games,
    scan_epic_games_manifests,
    scan_gog_games,
    scan_gog_galaxy_games,
    scan_standalone_games,
    scan_games,
    scan_all_games,
    find_best_game_exe,
    is_valid_executable,
    clean_game_name
)

__all__ = [
    "DiscoveredGame",
    "scan_epic_games",
    "scan_epic_games_manifests",
    "scan_gog_games",
    "scan_gog_galaxy_games",
    "scan_standalone_games",
    "scan_games",
    "scan_all_games",
    "find_best_game_exe",
    "is_valid_executable",
    "clean_game_name"
]
