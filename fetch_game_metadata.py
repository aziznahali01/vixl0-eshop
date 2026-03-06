import pandas as pd
import os
import re
import sqlite3
import time
from dotenv import load_dotenv
from steamgrid import SteamGridDB
import requests
from PIL import Image, ImageOps
from io import BytesIO

load_dotenv("api.env")

# -------------------------
# Load SteamGridDB Key
# -------------------------
STEAMGRID_KEY = os.getenv("STEAMGRID_KEY")
if not STEAMGRID_KEY:
    raise Exception("Missing SteamGridDB API key!")

os.makedirs("covers", exist_ok=True)

# -------------------------
# SteamGridDB Setup
# -------------------------
sgdb = SteamGridDB(STEAMGRID_KEY)

def get_steamgrid_cover(title):
    games = sgdb.search_game(title)
    if not games:
        print(f"[!] No SteamGridDB entry found for \"{title}\"")
        return ""
    game = games[0]  # pick first match

    grids = sgdb.get_grids_by_gameid([game.id])
    if not grids:
        print(f"[!] No grids found for game ID {game.id} (title: {title})")
        return ""

    # Filter only square PNG images
    square_grids = [g for g in grids if g.width == g.height and g.url.lower().endswith(".png")]
    if not square_grids:
        print(f"[!] No square grids found for \"{title}\"")
        return ""

    # Prefer 512x512 or 1024x1024
    preferred_sizes = [512, 1024]
    filtered = [g for g in square_grids if g.width in preferred_sizes]
    if filtered:
        grid = filtered[0]
    else:
        grid = square_grids[0]

    print(f"[i] Selected square cover for {title}: {grid.url}")
    return grid.url

def download_square_cover(url, save_path, size=512):
    if not url:
        return False
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGBA")

        # Resize proportionally and pad to square
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        square_img = Image.new("RGBA", (size, size), (0,0,0,0))
        x = (size - img.width) // 2
        y = (size - img.height) // 2
        square_img.paste(img, (x, y))
        square_img.save(save_path)
        return True
    except Exception as e:
        print(f"[!] Error downloading cover {save_path}: {e}")
        return False

# -------------------------
# Database setup
# -------------------------
db_file = "games.db"
conn = sqlite3.connect(db_file)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS games_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    platform TEXT,
    cover TEXT,
    file_id TEXT,
    direct_url TEXT
)
""")
conn.commit()

# -------------------------
# Read CSV
# -------------------------
input_csv = "drive_links.csv"
df = pd.read_csv(input_csv)

for index, row in df.iterrows():
    title = row["title"].strip()
    platform = row["platform"].strip()
    print(f"[i] Processing: {title} ({platform})")

    # Handle multiple files for PS1
    raw_file_id = str(row["file_id"]).strip()
    raw_direct_url = str(row["direct_url"]).strip()
    if platform.upper() == "PS1":
        file_id = "|".join([fid.strip() for fid in raw_file_id.split(",")])
        direct_url = "|".join([url.strip() for url in raw_direct_url.split(",")])
    else:
        file_id = raw_file_id
        direct_url = raw_direct_url

    # Clean filename: replace unsafe chars, remove extra underscores
    cover_filename = title.lower()
    cover_filename = re.sub(r"[^\w\s'-]", "", cover_filename)  # keep letters, numbers, spaces, ', -
    cover_filename = re.sub(r"\s+", "_", cover_filename)  # spaces -> underscore
    cover_filename = re.sub(r"_+", "_", cover_filename)  # remove double underscores
    cover_filename = f"{cover_filename}.png"
    cover_path = os.path.join("covers", cover_filename)

    # Download cover
    cover_url = get_steamgrid_cover(title)
    if cover_url:
        download_square_cover(cover_url, cover_path)
    else:
        cover_path = ""  # no cover available

    # Insert into DB
    try:
        cursor.execute("""
        INSERT OR IGNORE INTO games_metadata (title, platform, cover, file_id, direct_url)
        VALUES (?, ?, ?, ?, ?)
        """, (title, platform, cover_path, file_id, direct_url))
        conn.commit()
    except Exception as e:
        print(f"[!] DB insert error for {title}: {e}")

    time.sleep(0.25)  # API rate limit

conn.close()
print("All SteamGridDB covers processed and database updated!")
