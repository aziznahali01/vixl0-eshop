# Run Vixl0 eShop (Electron)

## 1) Prerequisites
- Install Node.js LTS (includes npm): https://nodejs.org
- Python must be available as `python` in PATH (used for SQLite reads)

## 2) Install dependencies
From project root:

```powershell
cd "E:\Vixl0 eShop"
npm install
```

## 3) Start app

```powershell
npm start
```

## 4) What this version does
- Loads games from `games.db` (`games_metadata` table)
- Renders consoles/franchises/store UI
- Uses local covers from `covers/`
- Real queue-based downloads with progress/speed/cancel
- Settings persisted in Electron user data folder

## 5) Notes
- Google Drive large-file anti-virus warning pages may block direct automation for some files.
- If a row has `direct_url`, that is preferred over `file_id`.
- Default download folder is controlled in Settings.
