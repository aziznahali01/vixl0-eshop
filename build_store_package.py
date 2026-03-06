# build_store_package.py
import os, sqlite3, json, csv, shutil, argparse, pathlib
from PIL import Image

APPDATA = os.environ.get("APPDATA")
DEFAULT_PLAYNITE_DB = os.path.join(APPDATA, "Playnite", "library.db") if APPDATA else None
OUT_DIR = "package"

def find_playnite_db(provided_path=None):
    if provided_path:
        if os.path.exists(provided_path):
            return provided_path
        raise FileNotFoundError(f"Provided Playnite DB not found: {provided_path}")
    if DEFAULT_PLAYNITE_DB and os.path.exists(DEFAULT_PLAYNITE_DB):
        return DEFAULT_PLAYNITE_DB
    raise FileNotFoundError("Playnite library.db not found. Provide path with --playnite-db")

def read_drive_links(csv_path="drive_links.csv"):
    mapping = {}
    if not os.path.exists(csv_path):
        print(f"[!] drive_links.csv not found at {csv_path}. Continuing without Drive links.")
        return mapping
    with open(csv_path, newline='', encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row: continue
            title = row[0].strip()
            url = row[1].strip() if len(row)>1 else ""
            # extract id
            fid = extract_drive_id(url)
            mapping[title.lower()] = fid
    return mapping

def extract_drive_id(url_or_id):
    if not url_or_id:
        return ""
    # If it looks like a google drive url, extract /d/<id>/ or id=...
    import re
    m = re.search(r"/d/([a-zA-Z0-9_-]{10,})", url_or_id)
    if m: return m.group(1)
    m = re.search(r"id=([a-zA-Z0-9_-]{10,})", url_or_id)
    if m: return m.group(1)
    # otherwise maybe the user pasted the id
    if re.match(r"^[a-zA-Z0-9_-]{10,}$", url_or_id):
        return url_or_id
    return url_or_id  # fallback

def prepare_output_dirs(out_dir=OUT_DIR):
    if os.path.exists(out_dir):
        print(f"[i] Removing existing {out_dir}")
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir,"assets","covers"), exist_ok=True)
    os.makedirs(os.path.join(out_dir,"assets","backgrounds"), exist_ok=True)
    os.makedirs(os.path.join(out_dir,"assets","screenshots"), exist_ok=True)
    return out_dir

def open_playnite_db(db_path):
    conn = sqlite3.connect(db_path)
    return conn

def table_exists(conn, tablename):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablename,))
    return cur.fetchone() is not None

def get_games_from_playnite(conn):
    # Try a couple of known table names/column patterns. Playnite schema can vary by version.
    cur = conn.cursor()
    possible_tables = ["Games", "Game", "LibraryGames", "Items"]
    table = None
    for t in possible_tables:
        if table_exists(conn, t):
            table = t
            break
    if not table:
        raise RuntimeError("Couldn't find a games table in Playnite DB. Tables found: " + ", ".join([r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]))
    print(f"[i] Using Playnite table: {table}")
    # identify useful columns by introspection
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    # heuristics
    col_name = next((c for c in cols if c.lower() in ("name","title","game_name")), None)
    col_descr = next((c for c in cols if "description" in c.lower() or "overview" in c.lower()), None)
    col_platform = next((c for c in cols if c.lower() in ("platform","platforms")), None)
    col_image = next((c for c in cols if "image" in c.lower() or "cover" in c.lower() or "background" in c.lower()), None)
    # fallback columns
    if not col_name:
        raise RuntimeError("Could not find a name/title column in Playnite DB table.")
    qcols = [col_name] + ([col_descr] if col_descr else []) + ([col_platform] if col_platform else []) + ([col_image] if col_image else [])
    q = f"SELECT {','.join(qcols)} FROM {table}"
    rows = cur.execute(q).fetchall()
    games = []
    for row in rows:
        rec = {}
        rec['title'] = row[0]
        rec['description'] = row[1] if col_descr else ""
        rec['platform'] = row[2] if col_platform else ""
        rec['imagepath'] = row[3] if col_image else ""
        games.append(rec)
    return games

def copy_and_normalize_image(src_path, dst_path):
    if not src_path:
        return False
    # Playnite sometimes stores relative paths or hash references; try multiple
    # If src_path is already a full path, copy; if not, search Playnite appdata Images folder
    if os.path.exists(src_path):
        shutil.copy(src_path, dst_path)
        return True
    # try APPDATA Playnite Images folder
    appdata = os.environ.get("APPDATA")
    candidate = None
    if appdata:
        candidate = os.path.join(appdata, "Playnite", "Images", src_path)
        if os.path.exists(candidate):
            shutil.copy(candidate, dst_path)
            return True
    # try to interpret it as a resource: maybe base64 or uri — skip
    return False

def build_local_games_db(out_dir, games_list, drive_map):
    dbpath = os.path.join(out_dir,"games.db")
    if os.path.exists(dbpath):
        os.remove(dbpath)
    conn = sqlite3.connect(dbpath)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE games (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT,
      platform TEXT,
      franchise TEXT,
      description TEXT,
      cover_path TEXT,
      background_path TEXT,
      screenshots_json TEXT,
      drive_file_id TEXT
    );
    """)
    conn.commit()
    for g in games_list:
        title = (g.get('title') or "").strip()
        platform = (g.get('platform') or "").strip()
        description = (g.get('description') or "") or ""
        normalized_title = title.lower().strip()
        drive_id = drive_map.get(normalized_title, "")
        cover_rel = g.get('cover_dst','')
        background_rel = g.get('background_dst','')
        screenshots_json = json.dumps([])
        cur.execute("INSERT INTO games (title, platform, franchise, description, cover_path, background_path, screenshots_json, drive_file_id) VALUES (?,?,?,?,?,?,?,?)",
                    (title, platform, "", description, cover_rel, background_rel, screenshots_json, drive_id))
    conn.commit()
    conn.close()
    print(f"[i] Wrote local games DB to {dbpath}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--playnite-db", help="Path to Playnite library.db (optional)")
    parser.add_argument("--drive-csv", default="drive_links.csv", help="CSV mapping title to drive url/id")
    args = parser.parse_args()
    dbpath = find_playnite_db(args.playnite_db)
    drive_map = read_drive_links(args.drive_csv)
    out = prepare_output_dirs()
    conn = open_playnite_db(dbpath)
    games = get_games_from_playnite(conn)
    print(f"[i] Found {len(games)} games in Playnite database (raw rows).")
    # copy images where possible
    for idx, g in enumerate(games):
        title = g.get('title') or f"game_{idx}"
        normalized = title.lower().strip()
        # try image path
        src_image = g.get('imagepath') or ""
        cover_dst_name = f"{idx}.png"
        cover_dst_rel = os.path.join("assets","covers",cover_dst_name)
        cover_dst = os.path.join(out,cover_dst_rel)
        ok = copy_and_normalize_image(src_image, cover_dst)
        if ok:
            g['cover_dst'] = cover_dst_rel
        else:
            g['cover_dst'] = ""
        # no background handling here, fallback empty
        g['background_dst'] = ""
    # build games.db
    build_local_games_db(out, games, drive_map)
    print("[i] Packaging complete. Inspect the 'package' folder. Zip it to share with friends.")

if __name__ == "__main__":
    main()
