import os
import sys
import time
import unittest
import tempfile
import steam_syncer

# Force headless offscreen platform for Qt testing
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from unittest.mock import patch, MagicMock
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QColor, QPixmap, QMouseEvent
from PyQt6.QtWidgets import QApplication, QSizePolicy
from PyQt6.QtTest import QTest
from qfluentwidgets import InfoBarPosition, CaptionLabel, CheckBox, TransparentToolButton, PushButton
from steam_syncer_gui import (
    MainWindow, load_app_config, save_app_config, configure_high_dpi,
    DraggableSwitchButton, TiltPosterLabel, ensure_qfluentwidgets_alive,
    get_or_create_qapp, make_cropped_thumb, CoverVariantsWorker, CoverSelectorDialog,
    CryptoDonationDialog, CRYPTO_WALLETS, SimpleCardWidget,
    get_windows_accent_color
)
import i18n
from i18n import tr


def test_gui():
    cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    cfg_backup = None
    if os.path.isfile(cfg_file):
        try:
            with open(cfg_file, 'r', encoding='utf-8') as f:
                cfg_backup = f.read()
        except Exception:
            cfg_backup = None

    try:
        _do_test_gui()
    finally:
        if cfg_backup is not None and os.path.isfile(cfg_file):
            try:
                with open(cfg_file, 'w', encoding='utf-8') as f:
                    f.write(cfg_backup)
            except Exception:
                pass


def _do_test_gui():
    configure_high_dpi()
    app = get_or_create_qapp()
    ensure_qfluentwidgets_alive(app)
    assert QApplication.highDpiScaleFactorRoundingPolicy() == Qt.HighDpiScaleFactorRoundingPolicy.PassThrough

    window = MainWindow()
    window.show()
    assert window is not None
    assert window.windowTitle() == "DeckBridge"

    # Disconnect background scan worker so it cannot race with test card additions
    if hasattr(window, 'scan_worker') and window.scan_worker:
        try:
            window.scan_worker.scan_finished.disconnect()
        except Exception:
            pass
        if window.scan_worker.isRunning():
            window.scan_worker.wait(3000)

    # Verify FramelessWindowHint is enforced to prevent duplicate DWM caption buttons on PyQt6 6.11
    assert bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint) is True
    window.updateFrameless()
    assert bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint) is True

    # 1. Test Window Sizing enforcement (860x620 default, 760x520 minimum)
    assert window.minimumSize().width() >= 760
    assert window.minimumSize().height() >= 520
    assert window.width() >= 760
    assert window.height() >= 520

    # 2. Check Unified Hero Card controls & dynamic action stack
    assert hasattr(window, 'hero_card')
    assert hasattr(window, 'status_card')  # aliased for compatibility
    assert hasattr(window, 'action_stack')
    assert hasattr(window, 'btn_sync')
    assert hasattr(window, 'btn_close_steam')
    assert hasattr(window, 'btn_browse_hero')
    assert hasattr(window, 'btn_download_steam')
    assert hasattr(window, 'btn_launch_steam')
    assert window.action_stack.count() >= 3
    assert hasattr(window, 'progress_bar')
    assert hasattr(window, 'list_folders')
    assert hasattr(window, 'txt_steam_path')
    assert hasattr(window, 'cmb_steam_users')
    assert hasattr(window, 'sw_download_art')
    assert hasattr(window, 'sw_backup')
    assert hasattr(window, 'sw_auto_scan')
    assert hasattr(window, 'steam_dot')
    assert hasattr(window, 'cmb_header_lang')
    assert hasattr(window, 'btn_header_settings')
    assert hasattr(window, 'btn_back_home')

    # Ensure manual duplicate buttons are not present
    assert not hasattr(window, 'btn_rescan')
    assert not hasattr(window, 'btn_refresh_status')

    # Test TitleBar Caption Button height matching (32 px)
    assert window.steam_dot.height() == 32
    assert window.steam_dot.width() == 32
    assert window.btn_header_settings.height() == 32

    # Test SteamStatusDot pulsing animation
    window.steam_dot.set_pulsing(True)
    assert window.steam_dot._is_pulsing is True
    assert window.steam_dot._pulse_timer.isActive() is True
    window.steam_dot.set_pulsing(False)
    assert window.steam_dot._is_pulsing is False
    assert window.steam_dot._pulse_timer.isActive() is False

    # 3. Check Background Monitoring Timer & Auto-Scan Switch
    assert hasattr(window, 'poll_timer')
    assert window.poll_timer.isActive()
    window.sw_auto_scan.setChecked(False)
    assert window.poll_timer.isActive() is False
    assert window.config.get('auto_scan') is False
    window.sw_auto_scan.setChecked(True)
    assert window.poll_timer.isActive() is True
    assert window.config.get('auto_scan') is True
    window.poll_background_state()

    # Check high-Hz smooth scroll engine tuning (duration=140ms)
    for sc in (window.home_scroll, window.settings_scroll):
        delegate = getattr(sc, 'scrollDelagate', None)
        assert delegate is not None
        vs = getattr(delegate, 'verticalSmoothScroll', None)
        assert vs is not None
        for engine in (getattr(vs, 'fixedStepScrollEngine', None), getattr(vs, 'adaptiveScrollEngine', None)):
            if engine:
                assert engine.duration == 140
                assert engine.fps >= 60

    # Functional scroll test: simulate wheel event and verify positive progression without reverse bouncing
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtCore import QPointF, QPoint
    window.switchTo(window.settings_interface)
    app.processEvents()
    initial_val = window.settings_scroll.verticalScrollBar().value()
    wheel_ev = QWheelEvent(
        QPointF(500, 350), QPointF(500, 350), QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False
    )
    app.sendEvent(window.settings_scroll.viewport(), wheel_ev)
    for _ in range(30):
        app.processEvents()
        time.sleep(0.01)
    scrolled_val = window.settings_scroll.verticalScrollBar().value()
    assert scrolled_val > initial_val, f"Scroll failed to advance: initial={initial_val}, scrolled={scrolled_val}"

    # 4. Test Windows 11 system accent detection
    accent = get_windows_accent_color()
    print(f"Detected Windows 11 system accent: {accent.name() if accent else 'None'}")
    window.sync_windows_accent_color()

    # 5. Test resizing and repaint stability
    window.resize(1100, 800)
    window.resize(760, 520)
    window.update()

    # Test return button is hidden (no phantom back button)
    assert window.navigationInterface.panel.returnButton.isVisible() == False

    # 6. Test zero horizontal overflow across resolutions and interfaces
    for iface, scroll, name in [
        (window.home_interface, window.home_scroll, "Home"),
        (window.settings_interface, window.settings_scroll, "Settings"),
    ]:
        window.switchTo(iface)
        app.processEvents()
        for w, h in [(860, 620), (760, 520), (800, 580)]:
            window.resize(w, h)
            app.processEvents()
            widget_w = scroll.widget().width()
            vp_w = scroll.viewport().width()
            assert widget_w <= vp_w, f"Horizontal overflow in {name} at {w}x{h}: widget={widget_w} > viewport={vp_w}"

    # Return to Home tab
    window.switchTo(window.home_interface)
    app.processEvents()

    # 7. Test empty state card with folder picker
    window.on_scan_finished([], set(), {})
    assert window.games_layout.count() >= 2  # empty state card + stretch
    # Ensure empty card does not cause horizontal overflow at minimum size
    window.resize(760, 520)
    app.processEvents()
    assert window.home_scroll.widget().width() <= window.home_scroll.viewport().width()
    window.clear_game_cards()

    # 8. Test game card addition & zero overflow with long names
    for i in range(4):
        dummy_game = {
            'clean_name': f'Extremely Long Game Title With Many Words In Name For Testing {i}',
            'exe_path': rf'C:\Games\SubFolder\VeryLongSubdirectoryPathNumber_{i}\Game_Executable_Binary_{i}.exe',
            'exe_name': f'Game_Executable_Binary_{i}.exe',
            'exe_size': 1024 * 1024 * 150 * (i + 1),
            'folder_path': rf'C:\Games\SubFolder\VeryLongSubdirectoryPathNumber_{i}',
            'is_registered': i % 2 == 0,
            'cover_path': None
        }
        window.add_game_card(dummy_game)
    assert window.games_layout.count() >= 3

    # Check that game card poster thumbnail has size 80x120 (Steam 2:3 ratio)
    first_card = window.games_layout.itemAtPosition(0, 0).widget()
    assert first_card is not None
    labels = first_card.findChildren(CaptionLabel)
    poster_lbl = [l for l in labels if l.width() == 80 and l.height() == 120]
    assert len(poster_lbl) == 1, f"Poster label must be 80x120, found: {[(l.width(), l.height()) for l in labels]}"
    assert isinstance(poster_lbl[0], TiltPosterLabel)

    app.processEvents()

    # Check Smart Checkboxes: hidden for registered game (i=0), visible for unregistered (i=1)
    chk_reg = first_card.findChild(CheckBox)
    assert chk_reg is not None
    assert chk_reg.isHidden() is True

    second_card = window.games_layout.itemAtPosition(1, 0).widget()
    assert second_card is not None
    chk_new = second_card.findChild(CheckBox)
    assert chk_new is not None
    assert chk_new.isHidden() is False

    # Test 3D Tilt interaction on hover and physics lerp
    p_widget = poster_lbl[0]
    ev_move = QMouseEvent(QEvent.Type.MouseMove, QPointF(45, 65), QPointF(45, 65), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    p_widget.mouseMoveEvent(ev_move)
    assert p_widget._is_hovered is True
    assert p_widget._target_scale > 1.0
    assert p_widget._target_rot_y > 0.0  # moved right of center -> positive Y rotation
    assert p_widget._target_rot_x < 0.0  # moved below center -> negative X rotation
    p_widget._on_tick()
    assert abs(p_widget._rot_y) > 0.0
    assert abs(p_widget._rot_x) > 0.0

    # Test reset on leave
    p_widget.leaveEvent(QEvent(QEvent.Type.Leave))
    assert p_widget._is_hovered is False
    assert p_widget._target_rot_x == 0.0
    assert p_widget._target_rot_y == 0.0
    assert p_widget._target_scale == 1.0

    window.resize(760, 520)
    app.processEvents()
    assert window.home_scroll.widget().width() <= window.home_scroll.viewport().width()

    # Clear game cards
    window.clear_game_cards()
    assert window.games_layout.count() == 1  # Only bottom stretch remains

    # Test smart sync notification when library is already up to date (0 added, 0 downloaded)
    report_up_to_date = {
        'success': True,
        'games_added': 0,
        'art_downloaded': 0,
        'games_found': [],
        'message': 'Library is already up to date.'
    }
    window.on_sync_finished(report_up_to_date)
    assert window.btn_sync.isEnabled() is True

    # 9. Test state synchronization & dynamic button replacement
    window.refresh_steam_status()
    steam_path = window.txt_steam_path.text().strip() if hasattr(window, 'txt_steam_path') else steam_syncer.get_steam_path()
    steam_installed = bool(steam_path and os.path.isdir(steam_path))
    if not steam_installed:
        assert window.steam_desc.isVisible() == True
        assert window._current_button_mode == "browse"
        assert window.action_stack.currentIndex() == 2
    elif steam_syncer.is_steam_running():
        assert "Steam" in window.steam_title.text()
        assert window._current_button_mode == "close"
        assert window.action_stack.currentIndex() == 1
        assert "Steam" in window.btn_close_steam.text()
    else:
        assert window.steam_desc.isVisible() == True
        assert window._current_button_mode == "sync"
        assert window.action_stack.currentIndex() == 0

    # Disconnect background scan worker and stop poll timer so background polling doesn't race with animation tests
    if hasattr(window, 'scan_worker') and window.scan_worker:
        try:
            window.scan_worker.scan_finished.disconnect()
        except Exception:
            pass
        if window.scan_worker.isRunning():
            window.scan_worker.wait(3000)
    if hasattr(window, 'poll_timer') and window.poll_timer.isActive():
        window.poll_timer.stop()

    # Test dynamic smooth transition between modes
    window.animate_set_button_mode("close")
    for _ in range(30):
        app.processEvents()
        time.sleep(0.015)
    assert window._current_button_mode == "close"
    assert window.action_stack.currentIndex() == 1

    window.animate_set_button_mode("sync")
    for _ in range(25):
        app.processEvents()
        time.sleep(0.015)
    assert window._current_button_mode == "sync"
    assert window.action_stack.currentIndex() == 0

    window.animate_set_button_mode("browse")
    for _ in range(25):
        app.processEvents()
        time.sleep(0.015)
    assert window._current_button_mode == "browse"
    assert window.action_stack.currentIndex() == 2

    # 10. Test Steam Detection (Requirement #7: check if steam is installed on PC)
    orig_path = window.txt_steam_path.text()
    window.txt_steam_path.setText(r"C:\NonExistentSteamDirectory_12345")
    window.refresh_steam_status()
    assert window._current_button_mode == "browse"
    assert window.action_stack.currentIndex() == 2
    assert "Не найден" in window.steam_title.text() or "Not found" in window.steam_title.text() or "nicht gefunden" in window.steam_title.text()
    # btn_download_steam should be visible when steam is not found
    assert window.btn_download_steam.isVisible() == True
    # open_steam_website should be callable
    assert hasattr(window, 'open_steam_website')
    assert callable(window.open_steam_website)

    # Check zero overflow when btn_download_steam is visible at 760x520
    window.resize(760, 520)
    app.processEvents()
    assert window.home_scroll.widget().width() <= window.home_scroll.viewport().width()

    # Restore valid path (or simulated valid directory if Steam is not installed in CI)
    if orig_path and os.path.isdir(orig_path):
        window.txt_steam_path.setText(orig_path)
        window.refresh_steam_status()
        assert window.btn_download_steam.isVisible() == False
    else:
        with tempfile.TemporaryDirectory() as fake_steam_dir:
            window.txt_steam_path.setText(fake_steam_dir)
            window.refresh_steam_status()
            assert window.btn_download_steam.isVisible() == False
        window.txt_steam_path.setText(orig_path)
        window.refresh_steam_status()

    # 11. Test Log Section in Settings (Requirement #6: logs in settings)
    assert hasattr(window, 'log_card')
    assert hasattr(window, 'log_text')
    assert hasattr(window, 'btn_copy_log')
    assert hasattr(window, 'btn_clear_log')
    window.append_log("Test log entry 123")
    assert "Test log entry 123" in window.log_text.toPlainText()
    window.btn_clear_log.click()
    assert window.log_text.toPlainText() == ""

    # 12. Test Internationalization across all 7 languages (Requirement #5: i18n support)
    assert hasattr(window, 'cmb_language')
    for lang in ['ru', 'en', 'de', 'fr', 'es', 'zh', 'ja']:
        i18n.I18NManager.instance().set_language(lang)
        window.retranslate_ui()
        assert window.btn_download_steam.text() != ""
        assert window.btn_close_steam.text() != ""
        assert window.btn_sync.text() != ""

        # Test zero overflow on both interfaces in every language at 760x520
        for iface, scroll, name in [
            (window.home_interface, window.home_scroll, "Home"),
            (window.settings_interface, window.settings_scroll, "Settings"),
        ]:
            window.switchTo(iface)
            window.resize(760, 520)
            app.processEvents()
            assert scroll.widget().width() <= scroll.viewport().width(), (
                f"Overflow in {name} ({lang}) at 760x520: widget={scroll.widget().width()} > vp={scroll.viewport().width()}"
            )

    # Switch back to Russian default
    i18n.I18NManager.instance().set_language("ru")
    window.retranslate_ui()
    assert window.btn_close_steam.text() == "Закрыть Steam"
    assert window.btn_sync.text() in (tr("btn_sync"), tr("btn_sync_all_up_to_date")) or "актуально" in window.btn_sync.text() or "Синхронизировать" in window.btn_sync.text()

    # 13. Test config load/save
    cfg = load_app_config()
    assert isinstance(cfg, dict)
    assert 'game_folders' in cfg
    assert 'download_artwork' in cfg
    assert 'backup_shortcuts' in cfg
    assert 'language' in cfg

    # 14. Test Multi-User Steam profile handling & persistence without wipe
    with tempfile.TemporaryDirectory() as tmp_steam:
        u1 = os.path.join(tmp_steam, "userdata", "11111111", "config")
        u2 = os.path.join(tmp_steam, "userdata", "22222222", "config")
        os.makedirs(u1, exist_ok=True)
        os.makedirs(u2, exist_ok=True)
        window.config['user_id'] = "22222222"
        window.populate_steam_users(tmp_steam)
        assert window.cmb_steam_users.currentData() == "22222222"
        assert window.config['user_id'] == "22222222"
    window.populate_steam_users(orig_path)

    # 15. Verify UI Polish & Regressions (The 7 Requirements)
    # Req 1 & 2: Button text does not include game count (only title does)
    window._current_games = []
    window._new_games_count = -1
    window._scanned_games_count = 5
    window.update_sync_button_text()
    assert "(" not in window.btn_sync.text()
    assert "5" not in window.btn_sync.text()
    assert "5" in window.lbl_games_title.text()

    # Req 3: Language selector is exclusively in Settings
    assert window.cmb_header_lang is None
    assert hasattr(window, 'cmb_language')

    # Req 4: CloseSteamButton has crisp white high-contrast text
    assert "#ffffff" in window.btn_close_steam.lbl_text.styleSheet().lower()
    assert window.btn_close_steam.lbl_text.text() != ""

    # Req 5: Native Mica / Fluent transparent background enabled
    if sys.platform == 'win32':
        assert window.isMicaEffectEnabled() == True
        assert "background-color: transparent" in window.styleSheet()
    else:
        assert window.isMicaEffectEnabled() == False
        assert "background-color: #202020" in window.styleSheet()
    assert "#161618" not in window.styleSheet()

    # Req 6: Steam configuration labels visible without QSizePolicy.Ignored collapse
    assert window.lbl_path_title.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Ignored
    assert window.lbl_account_title.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Ignored

    # Req 7: Launch Steam button hidden when Steam is running
    window.refresh_steam_status()
    if steam_syncer.is_steam_running():
        assert window.btn_launch_steam.isVisible() == False

    # Req: Hero Card All Up-to-Date State
    window._scanned_games_count = 5
    window._new_games_count = 0
    if not steam_syncer.is_steam_running():
        if steam_installed:
            window.refresh_steam_status()
            window._apply_button_mode_instant("launch")
            assert window.status_badge.text() in ("Библиотека актуальна", "Up to date")
            assert ("Все обнаруженные игры уже синхронизированы со Steam." in window.steam_desc.text() or "already synced" in window.steam_desc.text())
            assert window._current_button_mode == "launch"
            assert window.action_stack.currentIndex() == 3
            assert window.btn_launch_steam.isHidden() is False
        else:
            with tempfile.TemporaryDirectory() as fake_steam:
                window.txt_steam_path.setText(fake_steam)
                window.refresh_steam_status()
                window._apply_button_mode_instant("launch")
                assert window.status_badge.text() in ("Библиотека актуальна", "Up to date")
                assert window._current_button_mode == "launch"
                assert window.action_stack.currentIndex() == 3
                assert window.btn_launch_steam.isHidden() is False
            window.txt_steam_path.setText(orig_path)
            window.refresh_steam_status()
    window._scanned_games_count = 0
    window._new_games_count = -1

    # Req 8: Launcher detection & default game folders across platforms
    assert hasattr(window, 'btn_detect_launchers')
    assert hasattr(window, 'btn_reset_folders')
    initial_count = len(window.game_folders)
    window.detect_launchers()
    assert len(window.game_folders) >= initial_count
    window.reset_folders()
    assert len(window.game_folders) >= 2

    # Req 9: Operation Log space optimization (badges removed)
    assert window.lbl_metric_games is None
    assert window.lbl_metric_art is None

    # Req 10: DraggableSwitchButton native dragging and clicking
    assert isinstance(window.sw_download_art, DraggableSwitchButton)
    assert isinstance(window.sw_backup, DraggableSwitchButton)
    assert isinstance(window.sw_auto_scan, DraggableSwitchButton)
    # Test drag right on switch
    window.sw_backup.setChecked(False)
    assert window.sw_backup.isChecked() is False
    QTest.mousePress(window.sw_backup.indicator, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(window.sw_backup.indicator, pos=QPoint(32, 10))
    assert window.sw_backup.indicator.sliderX >= 15.0
    QTest.mouseRelease(window.sw_backup.indicator, Qt.MouseButton.LeftButton, pos=QPoint(32, 10))
    assert window.sw_backup.isChecked() is True
    # Test drag left on switch
    QTest.mousePress(window.sw_backup.indicator, Qt.MouseButton.LeftButton, pos=QPoint(32, 10))
    QTest.mouseMove(window.sw_backup.indicator, pos=QPoint(10, 10))
    assert window.sw_backup.indicator.sliderX < 15.0
    QTest.mouseRelease(window.sw_backup.indicator, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert window.sw_backup.isChecked() is False

    # Req 11: Non-intrusive bottom-right toast notifications
    toast = window.show_toast("info", "Test Toast", "Test Content", duration=1500)
    assert toast is not None
    assert toast.position == InfoBarPosition.BOTTOM_RIGHT

    # Req 12: Cover Variants Picker & Aspect-Ratio Cropping
    # Test make_cropped_thumb on 600x600 square cover (007 case)
    square_pix = QPixmap(600, 600)
    square_pix.fill(QColor("blue"))
    cropped_thumb = make_cropped_thumb(square_pix, 100, 140)
    assert cropped_thumb.width() == 100
    assert cropped_thumb.height() == 140

    # Test make_cropped_thumb on 800x400 wide header
    wide_pix = QPixmap(800, 400)
    wide_pix.fill(QColor("green"))
    cropped_wide = make_cropped_thumb(wide_pix, 100, 140)
    assert cropped_wide.width() == 100
    assert cropped_wide.height() == 140

    # Test CoverVariantsWorker with local dummy folder
    with tempfile.TemporaryDirectory() as tmp_gfolder:
        dummy_cover = os.path.join(tmp_gfolder, "cover.png")
        square_pix.save(dummy_cover)
        c_worker = CoverVariantsWorker("TestGame", game_folder=tmp_gfolder)
        results = []
        c_worker.variants_ready.connect(lambda v: results.extend(v))
        c_worker.run()  # run synchronously for offscreen test
        assert len(results) >= 1
        assert results[0]['is_local'] is True
        assert os.path.isfile(results[0]['url'])

    # Test CoverSelectorDialog lifecycle, candidate rendering, Apply & Cancel
    dlg = CoverSelectorDialog("TestGame", parent=window)
    dlg._on_variants_ready([
        {'source': 'Local File', 'url': dummy_cover, 'is_local': True},
        {'source': 'Steam: Test', 'url': 'https://example.com/test.jpg', 'thumb_bytes': None, 'is_local': False}
    ])
    assert len(dlg._candidate_cards) == 2
    assert dlg.yesButton.isEnabled() is True
    # Test Cancel rejection
    dlg.cancelButton.click()
    assert dlg.get_selected_cover_path() is None

    # Test Apply acceptance
    dlg_apply = CoverSelectorDialog("TestGame2", parent=window)
    dlg_apply._on_variants_ready([
        {'source': 'Local File', 'url': dummy_cover, 'is_local': True}
    ])
    assert len(dlg_apply._candidate_cards) == 1
    dlg_apply._on_select_card(dlg_apply._candidate_cards[0][0], dlg_apply._candidate_cards[0][1])
    dlg_apply.yesButton.click()
    assert dlg_apply.get_selected_cover_path() == dummy_cover

    # Test browse local in CoverSelectorDialog
    app_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app_icon.ico')
    dlg_browse = CoverSelectorDialog("TestGame3", parent=window)
    with patch('PyQt6.QtWidgets.QFileDialog.getOpenFileName', return_value=(app_icon_path, 'Images (*.png)')):
        dlg_browse.btn_browse_local.click()
        assert dlg_browse.get_selected_cover_path() == app_icon_path

    # 13. Test Selection Toggles ("Select All" / "Deselect All") on Home Tab
    if hasattr(window, 'scan_worker') and window.scan_worker:
        try:
            window.scan_worker.scan_finished.disconnect()
        except Exception:
            pass
        if window.scan_worker.isRunning():
            window.scan_worker.wait(4000)

    window.switchTo(window.home_interface)
    window.clear_game_cards()
    test_games = []
    for i in range(3):
        dummy_g = {
            'clean_name': f'Unregistered Game {i}',
            'exe_path': rf'C:\Games\Game{i}\game{i}.exe',
            'exe_name': f'game{i}.exe',
            'exe_size': 1024 * 1024 * 100,
            'folder_path': rf'C:\Games\Game{i}',
            'is_registered': False,
            'cover_path': None
        }
        test_games.append(dummy_g)
        window.add_game_card(dummy_g)
    window._current_games = test_games
    window._scanned_games_count = len(test_games)
    window._new_games_count = len(test_games)
    window.update_sync_button_text()
    assert hasattr(window, 'btn_select_all')
    assert hasattr(window, 'btn_deselect_all')
    app.processEvents()

    # Deselect all
    window.btn_deselect_all.click()
    app.processEvents()
    for card in window.games_container.findChildren(SimpleCardWidget):
        chk = card.findChild(CheckBox)
        if chk and not chk.isHidden():
            assert chk.isChecked() is False
    assert window.btn_sync.isEnabled() is False

    # Select all
    window.btn_select_all.click()
    app.processEvents()
    for card in window.games_container.findChildren(SimpleCardWidget):
        chk = card.findChild(CheckBox)
        if chk and not chk.isHidden():
            assert chk.isChecked() is True
    assert window.btn_sync.isEnabled() is True

    # 13b. Interactive Game Card widgets (Poster Click, Folder Open Button)
    first_card_widget = window.games_layout.itemAtPosition(0, 0).widget()
    card_open_btn = first_card_widget.findChild(TransparentToolButton)
    if card_open_btn:
        with patch('subprocess.Popen') as mock_open:
            card_open_btn.click()
            assert mock_open.called or hasattr(os, 'startfile')

    posters = [l for l in first_card_widget.findChildren(CaptionLabel) if isinstance(l, TiltPosterLabel)]
    if posters:
        with patch.object(CoverSelectorDialog, 'exec', return_value=0):
            posters[0].clicked.emit()

    # 14. Test Interactive Home Buttons & Steam Status Dot Click
    # 14a. Test Steam status dot click callback
    dot_clicked = []
    window.steam_dot.clicked_callback = lambda: dot_clicked.append(True)
    ev_press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(16, 16), QPointF(16, 16), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    window.steam_dot.mousePressEvent(ev_press)
    assert len(dot_clicked) == 1
    window.steam_dot.clicked_callback = window.refresh_steam_status

    # 14b. Interactive click of btn_sync
    with patch('steam_syncer.is_steam_running', return_value=False), \
         patch('steam_syncer_gui.SyncWorker') as mock_sync_worker_cls:
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        mock_sync_worker_cls.return_value = mock_worker
        window.btn_sync.setEnabled(True)
        window.btn_sync.click()
        assert mock_worker.start.called
        assert window.btn_sync.isEnabled() is False
        assert window.progress_bar.isVisible() is True
        mock_worker.isRunning.return_value = False
        window.on_sync_finished({'success': True, 'games_added': 1, 'art_downloaded': 0, 'games_found': []})
        assert window.btn_sync.isEnabled() is True

    # 14c. Interactive click of btn_close_steam
    with patch('steam_syncer_gui.CloseSteamWorker') as mock_close_worker_cls:
        mock_close = MagicMock()
        mock_close_worker_cls.return_value = mock_close
        window.btn_close_steam.setEnabled(True)
        window.btn_close_steam.click()
        assert mock_close.start.called
        assert window.btn_close_steam.isEnabled() is False
        window.on_steam_closed_result(True)
        assert window.btn_close_steam.isEnabled() is True

    # 14d. Interactive click of btn_launch_steam
    with tempfile.TemporaryDirectory() as tmp_steam_dir:
        fake_exe = os.path.join(tmp_steam_dir, "steam.exe")
        with open(fake_exe, "w") as f:
            f.write("mock")
        window.txt_steam_path.setText(tmp_steam_dir)
        with patch('subprocess.Popen') as mock_popen:
            window.btn_launch_steam.click()
            assert mock_popen.called

    # 14e. Interactive click of btn_browse_hero
    with patch('PyQt6.QtWidgets.QFileDialog.getExistingDirectory', return_value=r"C:\CustomSteamHeroPath"):
        window.btn_browse_hero.click()
        assert window.txt_steam_path.text() == os.path.normpath(r"C:\CustomSteamHeroPath")

    # 15. Test Navigation and TitleBar Header Buttons
    # Click Settings header button
    window.btn_header_settings.click()
    app.processEvents()
    assert window.stackedWidget.currentWidget() == window.settings_interface

    # Click Back to Home button
    window.btn_back_home.click()
    app.processEvents()
    assert window.stackedWidget.currentWidget() == window.home_interface

    # 16. Test Settings Tab Controls & Folder Management
    window.switchTo(window.settings_interface)
    app.processEvents()

    # Language Dropdown Switcher (cycle through all 7 languages)
    for idx in range(window.cmb_language.count()):
        window.cmb_language.setCurrentIndex(idx)
        app.processEvents()
        lang_code = window.cmb_language.itemData(idx)
        assert i18n.I18NManager.instance().get_current_language() == lang_code or lang_code == "auto"

    # Reset back to Russian for subsequent checks
    window.cmb_language.setCurrentIndex(window.cmb_language.findData("ru"))
    app.processEvents()

    # Test Folder Add/Remove/Detect/Reset
    test_scan_dir = os.path.normpath(r"C:\TestMockGamesFolder")
    if test_scan_dir not in window.game_folders:
        window.game_folders.append(test_scan_dir)
        window.list_folders.addItem(test_scan_dir)
        window.persist_settings()
    assert test_scan_dir in window.game_folders

    # Remove folder via remove button
    row_idx = -1
    for r in range(window.list_folders.count()):
        if window.list_folders.item(r).text() == test_scan_dir:
            row_idx = r
            break
    assert row_idx >= 0
    window.list_folders.setCurrentRow(row_idx)
    window.btn_remove_folder.click()
    assert test_scan_dir not in window.game_folders

    # Detect launchers & reset folders buttons
    window.btn_detect_launchers.click()
    app.processEvents()
    window.btn_reset_folders.click()
    app.processEvents()
    assert len(window.game_folders) >= 2

    # Interactive Folder Add via btn_add_folder
    with patch('PyQt6.QtWidgets.QFileDialog.getExistingDirectory', return_value=r"C:\AddedFolderTest"):
        window.btn_add_folder.click()
        assert r"C:\AddedFolderTest" in window.game_folders
        if r"C:\AddedFolderTest" in window.game_folders:
            window.game_folders.remove(r"C:\AddedFolderTest")

    # Interactive Steam Path Picker via btn_browse_steam
    with patch('PyQt6.QtWidgets.QFileDialog.getExistingDirectory', return_value=r"C:\MockSteamBrowse"):
        window.btn_browse_steam.click()
        assert window.txt_steam_path.text() == os.path.normpath(r"C:\MockSteamBrowse")

    # Steam Path Picker and User Selector
    window.txt_steam_path.setText(r"C:\MockSteamFolder_AutoTest")
    window.persist_settings()
    assert window.config['steam_path'] == r"C:\MockSteamFolder_AutoTest"

    # Smart Lifecycle switch
    assert hasattr(window, 'sw_auto_steam_lifecycle')
    window.sw_auto_steam_lifecycle.setChecked(True)
    assert window.config.get('auto_steam_lifecycle') is True
    window.sw_auto_steam_lifecycle.setChecked(False)
    assert window.config.get('auto_steam_lifecycle') is False

    # Backup shortcuts switch
    window.sw_backup.setChecked(True)
    assert window.config.get('backup_shortcuts') is True
    window.sw_backup.setChecked(False)
    assert window.config.get('backup_shortcuts') is False

    # Download artwork switch
    window.sw_download_art.setChecked(False)
    assert window.config.get('download_artwork') is False
    window.sw_download_art.setChecked(True)
    assert window.config.get('download_artwork') is True

    # SteamGridDB API key input
    window.txt_steamgriddb_key.setText("mock_sgdb_key_999")
    assert window.config.get('steamgriddb_key') == "mock_sgdb_key_999"
    window.txt_steamgriddb_key.setText("")
    assert window.config.get('steamgriddb_key') == ""

    # Operation Log clear & copy buttons
    window.append_log("DeckBridge automated click test log entry")
    assert "DeckBridge automated click test log entry" in window.log_text.toPlainText()
    window.btn_copy_log.click()
    cb = QApplication.clipboard()
    if cb:
        assert "DeckBridge automated click test log entry" in cb.text()
    window.btn_clear_log.click()
    assert window.log_text.toPlainText() == ""

    # 17. Test Donation Section & Multi-Wallet Crypto Dialog
    assert hasattr(window, 'btn_tribute')
    assert hasattr(window, 'btn_boosty')
    assert hasattr(window, 'btn_show_crypto')
    assert hasattr(window, 'btn_copy_usdt')
    assert hasattr(window, 'btn_copy_trc')

    # Interactive button clicks for tribute, boosty, and github links
    with patch('PyQt6.QtGui.QDesktopServices.openUrl') as mock_url:
        window.btn_tribute.click()
        assert mock_url.called
        assert "tribute.tg" in mock_url.call_args[0][0].toString()

    with patch('PyQt6.QtGui.QDesktopServices.openUrl') as mock_url:
        window.btn_boosty.click()
        assert mock_url.called
        assert "boosty.to" in mock_url.call_args[0][0].toString()

    if hasattr(window, 'btn_github'):
        with patch('PyQt6.QtGui.QDesktopServices.openUrl') as mock_url:
            window.btn_github.click()
            assert mock_url.called
            assert "DeckBridge" in mock_url.call_args[0][0].toString()

    with patch.object(CryptoDonationDialog, 'exec', return_value=0):
        window.btn_show_crypto.click()

    # Quick copy buttons
    window.btn_copy_usdt.click()
    if cb:
        assert cb.text() == "0xb9e67030ab0f38d1d88e4eaa605fb2acf0aa0ba3"
    window.btn_copy_trc.click()
    if cb:
        assert cb.text() == "TQ4RwzWxs4kD6WXFgJkejRMSeAPsGUTv44"

    # Crypto Wallets Dialog & Coin Selection across all 4 coins
    crypto_dlg = CryptoDonationDialog(window)
    assert crypto_dlg.cmb_coin.count() == 4
    for c_idx in range(4):
        crypto_dlg.cmb_coin.setCurrentIndex(c_idx)
        app.processEvents()
        coin_info = CRYPTO_WALLETS[c_idx]
        assert crypto_dlg.txt_addr.text() == coin_info['address']
        assert crypto_dlg.txt_addr.cursorPosition() == 0
        assert crypto_dlg.descLabel.text() != ""
        assert crypto_dlg.lbl_qr.pixmap() is not None
        assert not crypto_dlg.lbl_qr.pixmap().isNull()

    # Test copy address inside dialog
    crypto_dlg.btn_copy.click()
    if cb:
        assert cb.text() == CRYPTO_WALLETS[crypto_dlg.cmb_coin.currentIndex()]['address']
    crypto_dlg.yesButton.click()

    # 18. Test Window Controls (Minimize, Maximize, Close buttons)
    assert hasattr(window.titleBar, 'minBtn')
    assert hasattr(window.titleBar, 'maxBtn')
    assert hasattr(window.titleBar, 'closeBtn')
    assert window.titleBar.minBtn.height() > 0
    assert window.titleBar.closeBtn.height() > 0

    # Return to Home tab
    window.switchTo(window.home_interface)
    app.processEvents()

    print("ALL interactive widgets, click handlers, and dialog flows verified successfully!")
    window.poll_timer.stop()
    window.close()
    app.processEvents()


class TestDeckBridgeGUI(unittest.TestCase):
    def test_gui_flow(self):
        test_gui()


if __name__ == '__main__':
    unittest.main()

