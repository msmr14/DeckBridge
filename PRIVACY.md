# Privacy Policy for DeckBridge

**Last Updated: October 2026**

DeckBridge ("we", "our", or "the application") is an open-source, local-first desktop application designed to automatically scan local PC games, register them into Valve's Steam client (`shortcuts.vdf`), and download official high-resolution artwork capsules, hero banners, and logos.

This Privacy Policy describes our practices regarding the collection, storage, and use of information in compliance with **Microsoft Store Policy 10.5.1**, the General Data Protection Regulation (GDPR), and the California Consumer Privacy Act (CCPA).

---

## 1. Summary (Privacy First)

- **Zero Telemetry**: DeckBridge does not collect, record, track, or transmit any telemetry, crash reports, analytics, or behavioral data.
- **No Private Servers**: We do not operate remote tracking or collection servers. No personal information is ever sent to the author or any third-party marketing services.
- **Local-First Execution**: All shortcut modifications and folder scans occur exclusively on your local computer.

---

## 2. Information Accessed and Processed Locally

To provide its core functionality, DeckBridge accesses and processes the following data locally on your system:

1. **Steam Installation Paths and User IDs**:
   - DeckBridge locates local Steam installation directories (e.g. `C:\Program Files (x86)\Steam`) and numerical Steam account IDs found in `userdata` to locate `shortcuts.vdf` and the artwork `grid` directory.
   - This information is never transmitted outside your computer and is used solely to write game shortcuts and save grid artwork locally.

2. **Game Executables and Folder Names**:
   - The application scans directories you configure (e.g. `C:\Games`, `D:\Games`) to identify game executable files and clean folder names.
   - None of your game library paths, folder structures, or filenames are ever sent to remote tracking servers.

3. **Application Configuration**:
   - Preferences such as selected game directories, theme preferences, and language choices are stored locally in `%LOCALAPPDATA%\DeckBridge\config.json` (or adjacent to the portable executable).
   - Temporary and downloaded cover images are cached locally in `%LOCALAPPDATA%\DeckBridge\covers_cache`.

---

## 3. External Network Communications

DeckBridge only initiates outbound network requests to query public game metadata and download official artwork assets over encrypted HTTPS connections:

1. **Valve Steam Storefront & CDN**:
   - **Domains**: `store.steampowered.com`, `shared.cloudflare.steamstatic.com`, `cdn.cloudflare.steamstatic.com`.
   - **Purpose**: Anonymous search for public Steam AppIDs by game title, and downloading official game posters (600x900 portrait capsule), hero banners, logos, and horizontal header art.
   - **Data Sent**: The search term (game title). No Steam credentials, account passwords, or personal identifying tokens are ever sent.

2. **SteamGridDB API**:
   - **Domain**: `www.steamgriddb.com`.
   - **Purpose**: Querying alternative user-curated game artwork variants when configured by the user.
   - **Data Sent**: Game title query and an API key (if provided by the user).

---

## 4. Third-Party Libraries and SDKs

DeckBridge does not include any third-party advertisement networks, analytics SDKs (e.g., Google Analytics, Facebook SDK, Adjust), or crash reporters (e.g., Sentry, Firebase).

---

## 5. Data Retention and Deletion

All application data resides locally on your device. You can completely delete all stored data at any time by:
1. Deleting `%LOCALAPPDATA%\DeckBridge`
2. Deleting shortcut entries via the Steam client interface or deleting `shortcuts.vdf` backups in your Steam `userdata` folder.

---

## 6. Children's Privacy

DeckBridge does not knowingly collect or solicit any personal information from children under the age of 13.

---

## 7. Compliance and Contact

For questions regarding this Privacy Policy or DeckBridge's source code, please open an issue on the official GitHub repository:
- **GitHub Repository**: [https://github.com/msmr14/DeckBridge](https://github.com/msmr14/DeckBridge)
- **Issues**: [https://github.com/msmr14/DeckBridge/issues](https://github.com/msmr14/DeckBridge/issues)
