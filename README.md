<div align="center">

# DeckBridge

**Bridge non-Steam PC games seamlessly into Valve Steam, Big Picture, and Steam Deck with official high-resolution artwork.**

[![Release](https://img.shields.io/github/v/release/msmr14/DeckBridge?color=success&label=release)](https://github.com/msmr14/DeckBridge/releases/latest)
[![CI Test & Build](https://github.com/msmr14/DeckBridge/actions/workflows/build.yml/badge.svg)](https://github.com/msmr14/DeckBridge/actions/workflows/build.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Platform: Windows 11](https://img.shields.io/badge/platform-Windows%2011%20%7C%20Steam%20Deck-0078d4.svg)](https://www.microsoft.com/windows)
[![UI: Windows 11 Fluent](https://img.shields.io/badge/UI-Fluent%20Design%20Acrylic-informational.svg)](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)

</div>

---

## 📥 Download DeckBridge 1.0.0 / Скачать

| Package | Format | Target Platform | Link |
| :--- | :--- | :--- | :--- |
| **DeckBridge Portable** | `.zip` (Standalone) | Windows 10 & 11 (x64) | [DeckBridge-v1.0.0-Windows-x64.zip](https://github.com/msmr14/DeckBridge/releases/download/v1.0.0/DeckBridge-v1.0.0-Windows-x64.zip) |
| **DeckBridge Sideload** | `.msix` (Signed) | Windows 10 & 11 (x64) | [DeckBridge_1.0.0.0_x64_signed.msix](https://github.com/msmr14/DeckBridge/releases/download/v1.0.0/DeckBridge_1.0.0.0_x64_signed.msix) |
| **Microsoft Store** | `.msix` (Store Upload) | Partner Center Submission | [DeckBridge_1.0.0.0_x64.msix](https://github.com/msmr14/DeckBridge/releases/download/v1.0.0/DeckBridge_1.0.0.0_x64.msix) |

---

## 🎮 Overview / О проекте

**DeckBridge** is an open-source, local-first utility for Windows 11 and Steam Deck that automatically discovers non-Steam games across all drives and launchers (Epic Games, GOG, Amazon Games, EA App, Ubisoft Connect, Itch.io, standalone folders), registers them safely into Valve's Steam shortcuts (`shortcuts.vdf`), and fetches official high-resolution library artwork directly from Valve's official CDN and SteamGridDB.

---

## ✨ Key Features / Ключевые возможности

### 🛡️ Bulletproof `shortcuts.vdf` Safety
- **Steam Running Guard**: Live process detection via Windows API, `tasklist`, and PowerShell blocks modifications while `steam.exe` is active, preventing Steam from overwriting newly added shortcuts on exit.
- **Atomic File Writing**: Modifications are written to temporary files with `fsync()` before atomic swap (`os.replace`), preventing binary corruption.
- **Automated Backup Hierarchy**: Creates `shortcuts.vdf.bak` and timestamped historical snapshots before any write operation.
- **Integrity Validation**: Verifies VDF binary structure integrity prior to committing changes.

### 🎨 Official CDN Artwork Scraper (Zero API Key Needed)
- **Direct Valve Storefront CDN**: Queries Steam Storefront search API to retrieve official 4-piece artwork assets without requiring developer API keys:
  - **Portrait Capsule** (600x900 cover) &rarr; `{grid_id}p.png`
  - **Hero Banner** &rarr; `{grid_id}_hero.png`
  - **Logo with Transparency** &rarr; `{grid_id}_logo.png`
  - **Wide Header** &rarr; `{grid_id}.png`
- **Dual 32-bit & 64-bit Steam ID Compatibility**: Generates both traditional 32-bit Grid IDs and modern 64-bit Steam IDs required by recent Steam client releases (2024+), Big Picture, and Steam Deck.
- **SteamGridDB v2 Integration**: Optional support for custom community artwork via SteamGridDB API key.
- **Interactive Cover Selector**: One-click in-app gallery to review and choose alternative artwork variants.

### 🧠 Intelligent Game & Executable Discovery
- **Junk Filtering**: Filters out setup files, crash reporters, redistributables (`vcredist`, `dxsetup`), anti-cheat engines (`eac`, `battleye`), and helper utilities (`epicwebhelper`, `UnityCrashHandler`).
- **Launcher vs. Shipping Binary Detection**: Detects root game executables with heuristics prioritizing clean directory names and parent root wrappers over subfolder shipping binaries (`Binaries/Win64/*-Shipping.exe`).
- **Clean Naming Engine**: Strips release group tags (`-InsaneRamZes`, `[GOG]`, `[DRM-Free]`, `(Portable)`), version numbers (`v1.0.4`), and build identifiers (`Build 12345`).

### 🪟 Windows 11 Fluent UI
- **Native Acrylic Backdrop**: Hardware-accelerated real-time DWM Acrylic blur backdrop behind the window.
- **Dynamic Accent Synchronization**: Automatically syncs with the Windows 11 system accent color and adapts to Dark/Light themes.
- **Frameless Window Integration**: Custom Fluent title bar with Steam status indicator, refresh controls, and close buttons.
- **Internationalization (i18n)**: Fully localized into 7 languages:
  - English (`en-us`)
  - Русский (`ru-ru`)
  - Deutsch (`de-de`)
  - Français (`fr-fr`)
  - Español (`es-es`)
  - 简体中文 (`zh-hans`)
  - 日本語 (`ja-jp`)

---

## 📁 Project Structure

```
DeckBridge/
├── steam_syncer_gui.py      # Fluent Design GUI application
├── steam_syncer.py          # Standalone CLI core & VDF engine
├── steam_lifecycle.py       # Steam process lifecycle management
├── steam_vdf.py             # Binary shortcuts.vdf parser/writer
├── artwork_scraper.py       # Valve CDN and SteamGridDB scrapers
├── i18n.py                  # Multi-language localization manager
├── scanners/                # Game scanners (Epic, GOG, Standalone)
├── DeckBridge.spec          # PyInstaller packaging specification
├── Package.appxmanifest     # Windows App SDK / MSIX package manifest
├── config.example.json      # Default configuration template
├── PRIVACY.md               # Privacy Policy (MS Store Policy 10.5.1)
├── LICENSE                  # GNU General Public License v3.0
├── test_suite.py            # Backend unit & integration test suite
└── test_gui.py              # Headless GUI automated test suite
```

---

## 🚀 Quick Start / Быстрый запуск

### 1. Requirements
- Windows 10 (1809+) or Windows 11
- Python 3.12+ (if running from source)

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/msmr14/DeckBridge.git
cd DeckBridge

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. Launching

#### Graphical Interface (GUI)
```powershell
python steam_syncer_gui.py
# or double-click run_gui.bat
```

#### Command Line Interface (CLI)
```powershell
python steam_syncer.py "C:\Games" "D:\Games"
# or double-click run_cli.bat
```

**CLI Arguments**:
- `--dry-run`: Scan games and display planned changes without modifying any files.
- `--no-art`: Import shortcuts without downloading artwork.
- `--steam-path "C:\Path\To\Steam"`: Explicit Steam installation path.
- `--user-id "12345678"`: Target specific Steam user account ID.
- `-v`, `--verbose`: Enable detailed debug logging.

---

## 📦 Building Executable & MSIX Package

### Building Portable Executable with PyInstaller
```powershell
pyinstaller DeckBridge.spec --noconfirm
```
The compiled standalone build will be located in `dist/DeckBridge/`.

### MSIX Packaging for Microsoft Store
DeckBridge is architected for Microsoft Store and WindowsApps container compliance:
- Configuration is saved in `%LOCALAPPDATA%\DeckBridge\config.json`.
- Cover artwork cache is stored in `%LOCALAPPDATA%\DeckBridge\covers_cache`.
- All 7 UI languages are declared in `<Resources>` within `Package.appxmanifest`.
- No personal user paths or IDs are bundled in the package payload.

---

## 🗺️ Roadmap & Microsoft Store Certification

- [x] Windows 11 Acrylic blur & Fluent Design interface
- [x] Automatic Valve CDN artwork scraping (Capsule, Hero, Logo, Wide)
- [x] Multi-language support (EN, RU, DE, FR, ES, ZH, JA)
- [x] MSIX container compatibility (`%LOCALAPPDATA%` redirection)
- [x] Privacy Policy complying with Microsoft Store Policy 10.5.1
- [x] Automated GitHub Actions CI test & build pipeline
- [ ] Microsoft Partner Center submission and certification
- [ ] Direct Steam Deck Flatpak / Linux client release

---

## 🔒 Privacy & Safety

DeckBridge values your privacy:
- **Zero data collection**: No telemetry, no remote servers, no user tracking.
- Read the complete [Privacy Policy](PRIVACY.md).

---

## 📜 License

DeckBridge is open-source software licensed under the **GNU General Public License v3.0 (GPLv3)**. See [LICENSE](LICENSE) for details.
