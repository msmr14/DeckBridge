import os
import sys
import time
import unittest
import tempfile
import steam_syncer

# Force headless offscreen platform for Qt testing
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QColor, QPixmap, QMouseEvent
from PyQt6.QtWidgets import QApplication, QSizePolicy
from PyQt6.QtTest import QTest
from qfluentwidgets import InfoBarPosition, CaptionLabel, CheckBox
from steam_syncer_gui import (
    MainWindow, load_app_config, save_app_config, configure_high_dpi,
    DraggableSwitchButton, TiltPosterLabel, ensure_qfluentwidgets_alive,
    get_or_create_qapp, make_cropped_thumb, CoverVariantsWorker, CoverSelectorDialog,
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
    if steam_syncer.is_steam_running():
        assert "Steam" in window.steam_title.text()
        assert window._current_button_mode == "close"
        assert window.action_stack.currentIndex() == 1
        assert "Steam" in window.btn_close_steam.text()
    elif not steam_installed:
        assert window.steam_desc.isVisible() == True
        assert window._current_button_mode == "browse"
        assert window.action_stack.currentIndex() == 2
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
    assert window.isMicaEffectEnabled() == True
    assert "background-color: transparent" in window.styleSheet()
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

    # Test CoverSelectorDialog lifecycle and candidate rendering
    dlg = CoverSelectorDialog("TestGame", parent=window)
    dlg._on_variants_ready([
        {'source': 'Local File', 'url': dummy_cover, 'is_local': True},
        {'source': 'Steam: Test', 'url': 'https://example.com/test.jpg', 'thumb_bytes': None, 'is_local': False}
    ])
    assert len(dlg._candidate_cards) == 2
    assert dlg.yesButton.isEnabled() is True
    print("GUI automated tests PASSED successfully!")
    window.poll_timer.stop()
    window.close()
    app.processEvents()


class TestDeckBridgeGUI(unittest.TestCase):
    def test_gui_flow(self):
        test_gui()


if __name__ == '__main__':
    unittest.main()

