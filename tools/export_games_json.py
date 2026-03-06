import json
import os
import sqlite3

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(ROOT, "games.db")
OUT_DIR = os.path.join(ROOT, "data")
OUT_PATH = os.path.join(OUT_DIR, "games.json")


def infer_franchise(title: str) -> str:
    t = (title or "").lower()
    if "mario" in t or "luigi" in t:
        return "Mario"
    if "zelda" in t:
        return "Zelda"
    if "pokemon" in t or "pokémon" in t:
        return "Pokemon"
    if "kirby" in t:
        return "Kirby"
    if "sonic" in t:
        return "Sonic"
    if "persona" in t:
        return "Persona"
    if "crash" in t:
        return "Crash"
    if "donkey kong" in t or "diddy kong" in t:
        return "Donkey Kong"
    return "Other"


def first_part(value: str) -> str:
    if not value:
        return ""
    raw = str(value)
    for sep in ("|", ","):
        if sep in raw:
            raw = raw.split(sep)[0]
            break
    return raw.strip()


def main() -> None:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        "SELECT id,title,platform,description,size,cover,file_id,direct_url FROM games_metadata"
    ).fetchall()
    conn.close()

    os.makedirs(OUT_DIR, exist_ok=True)

    games = []
    for r in rows:
        title = r["title"] or "Unknown"
        games.append(
            {
                "id": r["id"],
                "title": title,
                "console": r["platform"] or "Unknown",
                "franchise": infer_franchise(title),
                "description": r["description"] or "No description available.",
                "size": r["size"] or "Unknown",
                "cover": r["cover"] or "",
                "driveFileId": first_part(r["file_id"] or ""),
                "directUrl": first_part(r["direct_url"] or ""),
            }
        )

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(games, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(games)} games to {OUT_PATH}")


if __name__ == "__main__":
    main()
