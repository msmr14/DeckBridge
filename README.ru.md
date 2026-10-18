<div align="right">
  <a href="README.md">English</a> | <b>Русский</b>
</div>

<div align="center">

# DeckBridge

**Бесшовный мост для добавления не-Steam игр в Valve Steam, Big Picture и Steam Deck с автоматической загрузкой официальных обложек высокого разрешения.**

[![Release](https://img.shields.io/github/v/release/msmr14/DeckBridge?color=success&label=версия)](https://github.com/msmr14/DeckBridge/releases/latest)
[![CI Test & Build](https://github.com/msmr14/DeckBridge/actions/workflows/build.yml/badge.svg)](https://github.com/msmr14/DeckBridge/actions/workflows/build.yml)
[![Лицензия: GPL v3](https://img.shields.io/badge/Лицензия-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Платформа: Windows 11](https://img.shields.io/badge/платформа-Windows%2011%20%7C%20Steam%20Deck-0078d4.svg)](https://www.microsoft.com/windows)
[![UI: Windows 11 Fluent](https://img.shields.io/badge/UI-Fluent%20Design%20Acrylic-informational.svg)](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
[![Поддержать: Tribute](https://img.shields.io/badge/Донат-Tribute%20%7C%20Crypto-ff69b4.svg)](https://web.tribute.tg/d/SsO)

</div>

---

## 📥 Скачать DeckBridge 1.0.0

| Пакет | Формат | Платформа | Ссылка |
| :--- | :--- | :--- | :--- |
| **DeckBridge Linux AppImage** | `.AppImage` (Один файл) | SteamOS (Steam Deck) и Linux (x64) | [**DeckBridge-x86_64.AppImage**](https://github.com/msmr14/DeckBridge/releases/latest) |
| **DeckBridge Linux Tarball** | `.tar.gz` (Архив с папкой) | SteamOS и Linux (x64) | [**DeckBridge-Linux-x64.tar.gz**](https://github.com/msmr14/DeckBridge/releases/latest) |
| **DeckBridge Windows Portable** | `.zip` (Портативная версия) | Windows 10 и 11 (x64) | [DeckBridge-v1.0.0-Windows-x64.zip](https://github.com/msmr14/DeckBridge/releases/download/v1.0.0/DeckBridge-v1.0.0-Windows-x64.zip) |
| **Microsoft Store** | Приложение Store | Windows 10 и 11 (x64) | *Скоро в Microsoft Store* |

> 💡 **Быстрый старт на Steam Deck:** Скачайте `DeckBridge-x86_64.AppImage` в режиме рабочего стола (Desktop Mode), разрешите запуск (`chmod +x DeckBridge-x86_64.AppImage`) и запустите двойным кликом! Также вы можете добавить AppImage в Steam как стороннюю игру и запускать прямо из игрового режима (Game Mode). DeckBridge работает 100% нативно без Proton или Wine!

---

## 🎮 О проекте

**DeckBridge** — это локальная open-source утилита для Windows 11 и Steam Deck, которая автоматически находит установленные игры на любых дисках и в лаунчерах (Epic Games, GOG, Amazon Games, EA App, Ubisoft Connect, Itch.io, отдельные папки и репаки), безопасно регистрирует их в ярлыках Steam (`shortcuts.vdf`) и скачивает официальные обложки высокой четкости напрямую из CDN Valve и базы SteamGridDB.

---

## 📸 Скриншоты интерфейса

<div align="center">

### 🎮 Обнаружение игр и автоматическая загрузка официального арта Steam
<img src="docs/screenshots/library_view.png" width="900" alt="Библиотека DeckBridge" style="border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);" />

<br/><br/>

### ⚙️ Настройки в стиле Fluent Design, контроль безопасности и поддержка автора
<img src="docs/screenshots/settings_view.png" width="900" alt="Настройки DeckBridge" style="border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);" />

</div>

---

## ✨ Ключевые возможности

### 🛡️ Неуязвимая безопасность `shortcuts.vdf`
* **Контроль активного процесса Steam**: Прямой мониторинг через Windows API и системные процессы блокирует запись, пока `steam.exe` активен, предотвращая перезапись ярлыков клиентом Steam при выходе.
* **Атомарная запись файлов**: Все изменения записываются во временный буфер со сбросом кэша на диск (`fsync`) перед мгновенной атомарной заменой (`os.replace`), исключая повреждение бинарного файла при сбоях.
* **Автоматические резервные копии**: Создание `shortcuts.vdf.bak` и снапшотов с метками времени перед любой операцией изменения.
* **Валидация целостности**: Проверка структуры бинарного дерева VDF перед сохранением.

### 🎨 Официальный загрузчик обложек Valve CDN (без API-ключей)
* **Прямой доступ к CDN Steam Storefront**: Запросы к каталогу Steam для загрузки полного комплекта из 4 элементов графики без регистрации ключей разработчика:
  * **Вертикальный постер** (капсула 600x900) &rarr; `{grid_id}p.png`
  * **Баннер-герой** &rarr; `{grid_id}_hero.png`
  * **Прозрачный логотип** &rarr; `{grid_id}_logo.png`
  * **Широкая шапка** &rarr; `{grid_id}.png`
* **Совместимость с 32-bit и 64-bit Steam ID**: Генерация как классических 32-битных Grid ID, так и современных 64-битных идентификаторов Steam, необходимых для новых сборок клиента (2024+), режима Big Picture и Steam Deck.
* **Интеграция со SteamGridDB v2**: Опциональная загрузка пользовательских фанатских постеров по бесплатному API-ключу.
* **Интерактивный выбор обложек**: Встроенная галерея для просмотра и выбора альтернативных постеров в один клик.

### 🧠 Умное сканирование и фильтрация мусора
* **Отсеивание вспомогательных файлов**: Фильтрация инсталляторов, краш-репортеров, библиотек (`vcredist`, `dxsetup`), античитов (`eac`, `battleye`) и служебных утилит (`epicwebhelper`, `UnityCrashHandler`).
* **Точное определение главного исполняемого файла**: Умные эвристики приоритета корневых файлов и лаунчеров над глубокими вспомогательными бинарниками (`Binaries/Win64/*-Shipping.exe`).
* **Очистка названий**: Удаление релиз-тегов (`-InsaneRamZes`, `[GOG]`, `[DRM-Free]`, `(Portable)`), номеров версий (`v1.0.4`) и номеров билдов (`Build 12345`).

### 🪟 Интерфейс Windows 11 Fluent Design
* **Аппаратный эффект Acrylic**: Системное размытие DWM Acrylic за окном приложения.
* **Синхронизация акцентного цвета**: Автоматическая адаптация под системный цвет темы Windows 11 и поддержка светлой/тёмной темы.
* **Интеграция заголовка**: Кастомная панель заголовка Fluent с индикатором статуса Steam, кнопками настроек и навигации.
* **Поддержка 7 языков**: Русский, Английский, Немецкий, Французский, Испанский, Упрощенный китайский и Японский с переключением на лету.

---

## 📁 Структура проекта

```
DeckBridge/
├── steam_syncer_gui.py      # Графический интерфейс Fluent Design
├── steam_syncer.py          # Ядро CLI и движок работы с VDF
├── steam_lifecycle.py       # Управление жизненным циклом процесса Steam
├── steam_vdf.py             # Бинарный парсер и генератор shortcuts.vdf
├── artwork_scraper.py       # Модуль загрузки арта из Valve CDN и SteamGridDB
├── i18n.py                  # Модуль мультиязычной локализации (7 языков)
├── scanners/                # Сканеры игр (Epic Games, GOG, отдельные папки)
├── DeckBridge.spec          # Спецификация сборки PyInstaller
├── Package.appxmanifest     # Манифест пакета Windows App SDK / MSIX
├── config.example.json      # Шаблон чистой конфигурации
├── PRIVACY.md               # Политика конфиденциальности (MS Store Policy 10.5.1)
├── LICENSE                  # Лицензия GNU General Public License v3.0
├── test_suite.py            # Набор тестов бэкенда и VDF
└── test_gui.py              # Автоматизированные тесты интерфейса
```

---

## 🚀 Быстрый запуск

### 1. Требования
* Windows 10 (1809+) или Windows 11
* Python 3.12+ (при запуске из исходного кода)

### 2. Клонирование и установка зависимостей
```powershell
# Клонировать репозиторий
git clone https://github.com/msmr14/DeckBridge.git
cd DeckBridge

# Создать и активировать виртуальное окружение
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Установить зависимости
pip install -r requirements.txt
```

### 3. Запуск

#### Графический интерфейс (GUI)
```powershell
python steam_syncer_gui.py
# или дважды кликните run_gui.bat
```

#### Консольная версия (CLI)
```powershell
python steam_syncer.py "C:\Games" "D:\Games"
# или дважды кликните run_cli.bat
```

**Параметры командной строки**:
* `--dry-run`: Сканировать игры и показать план действий без изменения файлов.
* `--no-art`: Импортировать игры без загрузки обложек.
* `--steam-path "C:\Путь\К\Steam"`: Явно указать путь к директории Steam.
* `--user-id "12345678"`: Указать конкретный аккаунт Steam.
* `-v`, `--verbose`: Включить подробный вывод журнала.

---

## 📦 Сборка из исходников и создание пакетов

### Сборка портативного .exe через PyInstaller
```powershell
pyinstaller DeckBridge.spec --noconfirm
```
Скомпилированный автономный дистрибутив будет находиться в каталоге `dist/DeckBridge/`.

### Архитектура пакета MSIX для Microsoft Store
DeckBridge полностью изолирован для безопасной работы внутри контейнера WindowsApps:
* Настройки хранятся в `%LOCALAPPDATA%\DeckBridge\config.json`.
* Кэш обложек сохраняется в `%LOCALAPPDATA%\DeckBridge\covers_cache`.
* Локализации объявлены в `<Resources>` манифеста `Package.appxmanifest`.
* Личные данные и пути исключены из тела пакета.

---

## 🗺️ Дорожная карта и релиз в Microsoft Store

- [x] Интерфейс Fluent Design с системным Acrylic-размытием Windows 11
- [x] Автоматический сборщик арта из Valve CDN (постер, баннер, логотип, шапка)
- [x] Поддержка 7 языков (EN, RU, DE, FR, ES, ZH, JA)
- [x] Полная изоляция контейнера MSIX (`%LOCALAPPDATA%`)
- [x] Политика конфиденциальности по стандарту Microsoft Store Policy 10.5.1
- [x] Автоматический пайплайн сборки и тестирования в GitHub Actions CI
- [ ] Публикация и сертификация в Microsoft Partner Center
- [ ] Прямой релиз сборки Flatpak для SteamOS / Linux

---

## 🔒 Приватность и безопасность

DeckBridge уважает конфиденциальность пользователей:
* **Нулевой сбор данных**: Никакой телеметрии, аналитики или сторонних серверов.
* Ознакомьтесь с полной [Политикой конфиденциальности](PRIVACY.md).

---

## ❤️ Поддержать разработчика

Если DeckBridge помогает вам легко и красиво организовывать библиотеку игр на ПК и Steam Deck, вы можете поддержать автора донатом на развитие проекта:

### 🧡 Boosty (Карты / СБП / Рубли)
* **Прямая ссылка:** [boosty.to/n300l/donate](https://boosty.to/n300l/donate)

[![Поддержать на Boosty](https://img.shields.io/badge/Донат-Boosty%20(Карты%20%2F%20СБП)-f15f2c?style=for-the-badge&logo=boosty&logoColor=white)](https://boosty.to/n300l/donate)

---

### 💳 Tribute (Банковские карты / Telegram / Stars)
Быстрый и удобный способ поддержать автора любой банковской картой, через Telegram Stars или криптовалютой:
* **Веб-версия (карты любых банков):** [web.tribute.tg/d/SsO](https://web.tribute.tg/d/SsO)
* **Telegram Mini App:** [t.me/tribute/app?startapp=dSsO](https://t.me/tribute/app?startapp=dSsO)

[![Поддержать через Tribute](https://img.shields.io/badge/Донат-Tribute%20(Карты%20%2F%20TG)-0088cc?style=for-the-badge&logo=telegram&logoColor=white)](https://web.tribute.tg/d/SsO)

---

### 🪙 Криптовалюта (USDT, USDC, Litecoin)

| Монета / Токен | Сеть (Network) | Адрес кошелька для депозита |
| :--- | :--- | :--- |
| **USDT** | **BNB Smart Chain (BSC / BEP20)** | `0xb9e67030ab0f38d1d88e4eaa605fb2acf0aa0ba3` |
| **USDT** | **TRON (TRC20)** | `TQ4RwzWxs4kD6WXFgJkejRMSeAPsGUTv44` |
| **USDC** | **Solana (SOL)** | `7SjWhmXyAQ2xVxB3BNuxHk1mQW8P5dg3aXVtr1eyT6qF` |
| **Litecoin (LTC)** | **Litecoin Network** | `LRBmSE6GuURdMJzTB971BAz4Z8Z9UXnPbF` |

<br />

<div align="center">
  <table>
    <tr>
      <td align="center"><b>USDT (BEP20)</b><br/><img src="Assets/donate_usdt_bep20.png" width="150" style="background:#ffffff;border-radius:8px;padding:4px;"/></td>
      <td align="center"><b>USDT (TRC20)</b><br/><img src="Assets/donate_usdt_trc20.png" width="150" style="background:#ffffff;border-radius:8px;padding:4px;"/></td>
      <td align="center"><b>USDC (SOL)</b><br/><img src="Assets/donate_usdc_sol.png" width="150" style="background:#ffffff;border-radius:8px;padding:4px;"/></td>
      <td align="center"><b>Litecoin (LTC)</b><br/><img src="Assets/donate_ltc.png" width="150" style="background:#ffffff;border-radius:8px;padding:4px;"/></td>
    </tr>
  </table>
  <sub><i>Сканируйте через Bybit, Binance, Trust Wallet, MetaMask, Phantom, OKX или любой Web3 кошелек</i></sub>
</div>

---

## 📜 Лицензия

DeckBridge является свободным программным обеспечением с открытым исходным кодом, распространяемым по лицензии **GNU General Public License v3.0 (GPLv3)**. Подробности см. в файле [LICENSE](LICENSE).
