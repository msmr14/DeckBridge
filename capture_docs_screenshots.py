#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automated screenshot generator for DeckBridge documentation.
Renders sanitized, pristine UI states for README and docs using native DirectWrite typography.
"""

import os
import sys
import tempfile
import time

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import QApplication

from qfluentwidgets import setTheme, Theme, CheckBox, CaptionLabel

import i18n
import steam_syncer
from steam_syncer_gui import (
    MainWindow, get_or_create_qapp, configure_high_dpi,
    CryptoDonationDialog, CoverSelectorDialog
)


def capture_all():
    configure_high_dpi()
    app = get_or_create_qapp()

    # Enforce Dark Theme
    setTheme(Theme.DARK)

    win = MainWindow()
    win.resize(940, 780)

    # Disconnect background threads
    if hasattr(win, 'scan_worker') and win.scan_worker:
        try:
            win.scan_worker.scan_finished.disconnect()
        except Exception:
            pass
        if win.scan_worker.isRunning():
            win.scan_worker.wait(2000)

    if hasattr(win, 'poll_timer') and win.poll_timer.isActive():
        win.poll_timer.stop()

    # Set English language for official README documentation screenshots
    i18n.I18NManager.instance().set_language('en')
    win.retranslate_ui()

    # Provide a rich Fluent Dark background canvas for clean grabs
    win.setStyleSheet("""
        MainWindow, #homeInterface, #settingsInterface {
            background-color: #18181b;
        }
    """)

    # Setup Hero Card state
    win.hero_card.setStyleSheet("""
        SimpleCardWidget {
            background-color: rgba(30, 30, 34, 0.75);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
        }
    """)
    win.steam_desc.setText('Steam is closed and ready for safe shortcut synchronization.')
    win.status_badge.setText('Ready to sync')
    win.status_badge.setStyleSheet(
        'color: #81c784; background: rgba(76, 175, 80, 0.20); '
        'border: 1px solid rgba(76, 175, 80, 0.35); '
        'padding: 3px 10px; border-radius: 4px; font-weight: 600; font-size: 11px;'
    )
    win._apply_button_mode_instant('sync')
    win.btn_sync.setEnabled(True)
    win.btn_sync.setText('Sync to Steam (2 new)')

    # Download or load sample covers
    covers_dir = os.path.join(tempfile.gettempdir(), 'deckbridge_doc_covers')
    os.makedirs(covers_dir, exist_ok=True)

    apps = [
        (1091500, 'Cyberpunk 2077', r'C:\Games\Cyberpunk 2077\bin\x64', 'Cyberpunk2077.exe', 64.2, True),
        (1086940, "Baldur's Gate 3", r'D:\Games\Baldurs Gate 3\bin', 'bg3_dx11.exe', 122.4, True),
        (1245620, 'ELDEN RING', r'C:\Games\ELDEN RING\Game', 'eldenring.exe', 48.6, False),
        (1145350, 'Hades II', r'C:\Games\Hades II', 'Hades2.exe', 8.5, False)
    ]

    win.clear_game_cards()
    sample_games = []

    for appid, name, folder, exe, size_gb, is_reg in apps:
        c_path = os.path.join(covers_dir, f'{appid}.jpg')
        if not os.path.isfile(c_path):
            url = f'https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg'
            r = steam_syncer.safe_requests_get(url)
            if r and r.status_code == 200:
                with open(c_path, 'wb') as f:
                    f.write(r.content)
        g_info = {
            'clean_name': name,
            'exe_path': os.path.join(folder, exe),
            'exe_name': exe,
            'exe_size': int(size_gb * 1024 * 1024 * 1024),
            'folder_path': folder,
            'is_registered': is_reg,
            'cover_path': c_path if os.path.isfile(c_path) else None,
            'selected': not is_reg
        }
        sample_games.append(g_info)
        win.add_game_card(g_info)

    win._current_games = sample_games
    win._scanned_games_count = len(sample_games)
    win._new_games_count = 2
    win.update_sync_button_text()
    win.btn_select_all.setText('Select All')
    win.btn_deselect_all.setText('Deselect All')

    win.show()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)

    # Capture 1: Library View
    os.makedirs('docs/screenshots', exist_ok=True)
    pix_lib = win.grab()
    pix_lib.save('docs/screenshots/library_view.png')
    print(f"Captured docs/screenshots/library_view.png ({pix_lib.width()}x{pix_lib.height()})")

    # Capture 2: Settings View
    win.switchTo(win.settings_interface)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)

    win.list_folders.clear()
    for d in [r'C:\Games', r'D:\Games', r'C:\Program Files\Epic Games', r'C:\Program Files (x86)\GOG Galaxy\Games']:
        win.list_folders.addItem(d)

    win.txt_steam_path.setText(r'C:\Program Files (x86)\Steam')
    win.cmb_steam_users.clear()
    win.cmb_steam_users.addItem('PlayerOne [ID: 76561198000000000]', userData='76561198000000000')

    # Scroll to top
    win.settings_scroll.verticalScrollBar().setValue(0)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)

    pix_set = win.grab()
    pix_set.save('docs/screenshots/settings_view.png')
    print(f"Captured docs/screenshots/settings_view.png ({pix_set.width()}x{pix_set.height()})")

    # Capture 3: Crypto Wallets Dialog
    crypto_dlg = CryptoDonationDialog(parent=win, default_coin_idx=0)
    crypto_dlg.show()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    pix_crypto = crypto_dlg.grab()
    pix_crypto.save('docs/screenshots/crypto_wallets_dialog.png')
    print(f"Captured docs/screenshots/crypto_wallets_dialog.png ({pix_crypto.width()}x{pix_crypto.height()})")
    crypto_dlg.close()

    # Clean up scratch files
    if os.path.isfile('test_font_render.png'):
        try:
            os.remove('test_font_render.png')
        except Exception:
            pass

    win.close()
    app.processEvents()
    print("Screenshots updated successfully!")


if __name__ == '__main__':
    capture_all()
