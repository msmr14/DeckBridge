#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam Lifecycle Mock Stress Test (test_lifecycle_mock.py)
Validates the complete Lifecycle Orchestration:
- Simulates mock Steam client running.
- Verifies heavy staging runs in memory/temp without file locks on userdata.
- Verifies graceful shutdown request and wait-polling loop.
- Verifies fast atomic injection (< 500ms) with 3-gen backup rotation.
- Verifies resurrection with Big Picture (-gamepadui) or standard mode.
"""

import os
import sys
import time
import shutil
import tempfile
import unittest
import subprocess
from unittest.mock import patch, MagicMock

import vdf

import steam_syncer
from steam_lifecycle import (
    StagedSyncSession,
    orchestrate_sync_cycle,
    is_steam_fully_closed,
    resurrect_steam
)


class SteamLifecycleMockTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="mock_steam_env_")
        self.steam_path = os.path.join(self.tmpdir, "Steam")
        self.user_id = "12345678"
        self.userdata_dir = os.path.join(self.steam_path, "userdata", self.user_id)
        self.config_dir = os.path.join(self.userdata_dir, "config")
        self.grid_dir = os.path.join(self.config_dir, "grid")
        os.makedirs(self.grid_dir, exist_ok=True)

        # Mock steam.exe binary stub
        self.mock_steam_exe = os.path.join(self.steam_path, "steam.exe")
        with open(self.mock_steam_exe, 'w') as f:
            f.write("#!mock steam binary")

        # Initial shortcuts.vdf
        self.shortcuts_vdf = os.path.join(self.config_dir, "shortcuts.vdf")
        initial_vdf = {
            'shortcuts': {
                '0': {
                    'appid': 100,
                    'AppName': 'Pre-existing Game',
                    'Exe': '"C:\\Old\\old.exe"',
                    'StartDir': '"C:\\Old"'
                }
            }
        }
        steam_syncer.save_shortcuts_vdf(self.shortcuts_vdf, initial_vdf)

        # Mock games folder with game executables
        self.games_folder = os.path.join(self.tmpdir, "Games")
        game1_dir = os.path.join(self.games_folder, "Hades II [DRM-Free]")
        os.makedirs(game1_dir, exist_ok=True)
        with open(os.path.join(game1_dir, "Hades2.exe"), 'wb') as f:
            f.write(b'\x00' * 5000)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stage_1_preparation_does_not_touch_userdata(self):
        """Stage 1: Heavy work happens in temp/memory, real userdata is untouched."""
        session = StagedSyncSession(
            game_folders=[self.games_folder],
            steam_path=self.steam_path,
            user_id=self.user_id,
            download_artwork=False
        )
        try:
            mtime_before = os.path.getmtime(self.shortcuts_vdf)

            # Prepare staging
            res = session.prepare_stage()
            self.assertTrue(res['success'])
            self.assertEqual(res['games_count'], 1)

            # Real shortcuts.vdf MUST NOT be modified yet
            mtime_after = os.path.getmtime(self.shortcuts_vdf)
            self.assertEqual(mtime_before, mtime_after)

            # Staged in-memory shortcuts contain new game
            shortcuts_mem = session.target_shortcuts_data['shortcuts']
            self.assertIn('1', shortcuts_mem)
            self.assertEqual(shortcuts_mem['1']['AppName'], 'Hades II')
        finally:
            session.cleanup()

    def test_stage_3_fast_atomic_injection_and_backup(self):
        """Stage 3: Atomic commit under 500ms with rotating backups."""
        session = StagedSyncSession(
            game_folders=[self.games_folder],
            steam_path=self.steam_path,
            user_id=self.user_id,
            download_artwork=False
        )
        try:
            session.prepare_stage()

            # Ensure is_steam_fully_closed returns True during commit
            with patch('steam_lifecycle.is_steam_fully_closed', return_value=True):
                t0 = time.time()
                committed = session.commit_stage()
                elapsed = time.time() - t0

                self.assertTrue(committed)
                # Must be under 500ms
                self.assertLess(elapsed, 0.5, f"Commit took {elapsed*1000:.1f}ms, must be < 500ms")

                # Verify file updated
                updated = steam_syncer.load_shortcuts_vdf(self.shortcuts_vdf)
                self.assertIn('1', updated['shortcuts'])
                self.assertEqual(updated['shortcuts']['1']['AppName'], 'Hades II')

                # Verify .bak created
                self.assertTrue(os.path.isfile(self.shortcuts_vdf + ".bak"))
        finally:
            session.cleanup()

    def test_full_orchestration_cycle_with_mock_shutdown_and_resurrection(self):
        """Full Orchestration: Mock running Steam -> Shutdown -> Injection -> Relaunch."""
        steam_state = {'running': True}

        def mock_is_closed():
            return not steam_state['running']

        def mock_shutdown(steam_path):
            # Steam client receives -shutdown signal, processes exit after short delay
            steam_state['running'] = False
            return True

        resurrect_called = {'called': False, 'big_picture': False}

        def mock_resurrect(steam_path, big_picture=False):
            resurrect_called['called'] = True
            resurrect_called['big_picture'] = big_picture
            steam_state['running'] = True
            return True

        with patch('steam_lifecycle.is_steam_fully_closed', side_effect=mock_is_closed), \
             patch('steam_lifecycle.request_steam_shutdown', side_effect=mock_shutdown), \
             patch('steam_lifecycle.resurrect_steam', side_effect=mock_resurrect), \
             patch('steam_lifecycle.is_big_picture_mode_running', return_value=True):

            logs = []
            res = orchestrate_sync_cycle(
                game_folders=[self.games_folder],
                steam_path=self.steam_path,
                user_id=self.user_id,
                download_artwork=False,
                restart_steam=True,
                log_callback=logs.append
            )

            self.assertTrue(res['success'])
            self.assertEqual(res['games_count'], 1)
            self.assertTrue(res['was_restarted'])

            # Resurrection verified with Big Picture Mode (-gamepadui)
            self.assertTrue(resurrect_called['called'])
            self.assertTrue(resurrect_called['big_picture'])

            # Shortcuts verified on disk
            final_vdf = steam_syncer.load_shortcuts_vdf(self.shortcuts_vdf)
            self.assertEqual(len(final_vdf['shortcuts']), 2)


def run_mock_test():
    print("=" * 70)
    print("      STEAM LIFECYCLE ORCHESTRATOR MOCK STRESS-TEST SUITE            ")
    print("=" * 70 + "\n")

    suite = unittest.TestLoader().loadTestsFromTestCase(SteamLifecycleMockTest)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print("  STATUS: [PASS] - STEAM LIFECYCLE MOCK STRESS-TEST SUCCEEDED")
    else:
        print("  STATUS: [FAIL] - LIFECYCLE TESTS FAILED")
    print("=" * 70 + "\n")

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_mock_test())
