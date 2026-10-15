#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DiscoveredGame Model (scanners/discovered_game.py)
Unified data model for games discovered from Standalone, Epic Games, and GOG Galaxy.
Conforms to DiscoveredGame(name, exe_path, start_dir, source).
Inherits from dict for 100% backwards compatibility with dictionary item access.
"""

import os
from typing import Any


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
        
        # Clean name resolution
        from steam_syncer import clean_game_name
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
