# Build Windows Installer / EXE

## One-time setup
```powershell
cd "E:\Vixl0 eShop"
npm.cmd install
```

## Build both installer + portable exe
```powershell
npm.cmd run dist:win
```

Outputs will be in:
- `E:\Vixl0 eShop\release\Vixl0 eShop-<version>-nsis.exe` (installer)
- `E:\Vixl0 eShop\release\Vixl0 eShop-<version>-portable.exe` (portable)

## Build only installer
```powershell
npm.cmd run dist:installer
```

## Build only portable exe
```powershell
npm.cmd run dist:portable
```

## How updates work
1. Bump version in `package.json` (for example `1.0.0` -> `1.0.1`).
2. Rebuild with `npm.cmd run dist:win`.
3. Share the new installer/exe with friends.

## Data source for packaged app
Build scripts export `games.db` into `data/games.json` before packaging.
- Script: `tools/export_games_json.py`
- Runtime reads `data/games.json` first.

If you edit DB content, rebuild so the JSON snapshot is refreshed.
