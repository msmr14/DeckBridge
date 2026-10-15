#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SteamGridDB & Valve CDN Artwork Downloader (artwork_scraper.py)
Downloads all 4 graphic asset types (poster, hero, logo, icon, and wide grid)
from SteamGridDB API v2 with automatic fallback to official Valve CDN.
"""

from typing import Dict, List, Tuple, Any, Optional
from steam_syncer import (
    SteamGridDBClient,
    DEFAULT_STEAMGRIDDB_KEY,
    download_artwork_for_game,
    search_steam_store_appid,
    fetch_appdetails_assets,
    convert_and_save_image,
    is_safe_artwork_url,
    is_safe_grid_path
)

# Convenient aliases
download_artwork = download_artwork_for_game
download_game_artwork = download_artwork_for_game
search_steam_store = search_steam_store_appid

__all__ = [
    "SteamGridDBClient",
    "DEFAULT_STEAMGRIDDB_KEY",
    "download_artwork",
    "download_game_artwork",
    "download_artwork_for_game",
    "search_steam_store",
    "search_steam_store_appid",
    "fetch_appdetails_assets",
    "convert_and_save_image",
    "is_safe_artwork_url",
    "is_safe_grid_path"
]
