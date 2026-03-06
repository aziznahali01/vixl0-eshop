import sqlite3
import re
import os

db_file = "games.db"
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

# Fetch all records with cover paths
cursor.execute("SELECT id, cover FROM games_metadata")
rows = cursor.fetchall()

for row in rows:
    game_id, cover_path = row
    if cover_path:
        dirname = os.path.dirname(cover_path)
        filename = os.path.basename(cover_path)

        # Replace ":" with "_" and collapse multiple underscores
        safe_name = filename.replace(":", "_")
        safe_name = re.sub(r"_+", "_", safe_name)  # collapse multiple underscores

        safe_path = os.path.join(dirname, safe_name)

        # Rename the actual file if it exists
        if os.path.exists(cover_path) and cover_path != safe_path:
            os.rename(cover_path, safe_path)
            print(f"[i] Renamed file: {cover_path} -> {safe_path}")

        # Update the DB with the safe path
        cursor.execute("UPDATE games_metadata SET cover=? WHERE id=?", (safe_path, game_id))

conn.commit()
conn.close()
print("All cover paths cleaned and updated in the database!")
