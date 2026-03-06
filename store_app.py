# store_app_ctk.py
# Updated launcher with compact UI, single console row, bold titles, size display,
# download manager queue with progress, settings download folder, and wrapped descriptions.

import os
import sys
import sqlite3
import threading
import requests
import time
import math
import queue
import re
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageOps, ImageTk
import pandas as pd
import customtkinter as ctk
from tkinter import filedialog, messagebox
import gdown

# ---------- Config ----------
APP_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(APP_DIR, "games.db")           # expects games_metadata table
COVERS_DIR = os.path.join(APP_DIR, "covers")
DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Downloads")
THUMB_SIZE = (400, 400)        # large display used in details
THUMB_DISPLAY = (220, 220)     # displayed in tile
TILE_SIZE = (240, 320)
CTK_THEME = "dark"
MAX_PARALLEL_DOWNLOADS = 3     # number of concurrent download threads
# ----------------------------

ctk.set_appearance_mode(CTK_THEME)
ctk.set_default_color_theme("dark-blue")

# ---------- Helpers ----------
def safe_filename(name: str) -> str:
    s = name.lower()
    s = re.sub(r'[<>:"/\\|?*]', '', s)   # remove forbidden windows chars
    s = re.sub(r"[^\w\s'-]", "", s)      # keep letters, numbers, space, -, '
    s = re.sub(r"\s+", "_", s.strip())
    s = re.sub(r"_+", "_", s)
    return s

def load_image_thumbnail(path, size):
    try:
        img = Image.open(path).convert("RGBA")
        img.thumbnail(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", size, (0,0,0,0))
        x = (size[0] - img.width)//2
        y = (size[1] - img.height)//2
        canvas.paste(img, (x,y), img if img.mode == "RGBA" else None)
        return ImageTk.PhotoImage(canvas)
    except Exception:
        # fallback blank image
        canvas = Image.new("RGBA", size, (34,34,34,255))
        return ImageTk.PhotoImage(canvas)

def get_extension_from_headers(headers, fallback='.bin'):
    cd = headers.get('content-disposition', '')
    if 'filename=' in cd:
        # try extract filename
        m = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^;"\']+)', cd, flags=re.I)
        if m:
            fn = m.group(1)
            _, ext = os.path.splitext(fn)
            if ext:
                return ext
    # try content-type
    ct = headers.get('content-type','').lower()
    if 'zip' in ct: return '.zip'
    if 'iso' in ct: return '.iso'
    if 'audio' in ct: return '.bin'
    if 'octet-stream' in ct: return '.bin'
    return fallback

# ---------- Download Manager (global queue) ----------
class DownloadTask:
    def __init__(self, file_id, url, dest_path, callback_progress=None, callback_done=None, index_in_game=0):
        self.file_id = file_id  # likely a Google Drive ID
        self.url = url          # direct url fallback
        self.dest_path = dest_path
        self.callback_progress = callback_progress
        self.callback_done = callback_done
        self.index_in_game = index_in_game
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

class DownloadManager:
    def __init__(self, concurrency=MAX_PARALLEL_DOWNLOADS):
        self.queue = queue.Queue()
        self.concurrency = concurrency
        self.threads = []
        self.running = False
        self.session = requests.Session()
        self.lock = threading.Lock()
        self.tasks = {}

    def start(self):
        if self.running: return
        self.running = True
        for i in range(self.concurrency):
            t = threading.Thread(target=self.worker, daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        self.running = False
        # threads are daemon; they exit when program ends

    def enqueue(self, task: DownloadTask):
        with self.lock:
            self.tasks[id(task)] = task
        self.queue.put(task)
        self.start()

    def cancel_task(self, task_id):
        with self.lock:
            task = self.tasks.get(task_id)
        if not task:
            return False
        task.cancel()
        return True

    def worker(self):
        while self.running:
            try:
                task = self.queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._download_task(task)
            except Exception as e:
                if task.callback_done:
                    task.callback_done(False, str(e))
                with self.lock:
                    self.tasks.pop(id(task), None)
            self.queue.task_done()

    def _download_task(self, task: DownloadTask):
        if task.cancel_event.is_set():
            if task.callback_done:
                task.callback_done(False, "Cancelled")
            return
        # Prefer Google Drive download using file_id if possible
        # Otherwise use direct URL if provided
        if task.file_id:
            try:
                self._download_google_drive(task.file_id, task.dest_path, task.callback_progress)
                if task.callback_done:
                    task.callback_done(True, task.dest_path)
                with self.lock:
                    self.tasks.pop(id(task), None)
                return
            except Exception as e:
                # fallback to direct URL
                pass
        if task.url:
            # simple requests download
            r = self.session.get(task.url, stream=True, timeout=20)
            r.raise_for_status()
            total = r.headers.get('Content-Length')
            total = int(total) if total and total.isdigit() else None
            bytes_so_far = 0
            started = time.time()
            ext = get_extension_from_headers(r.headers, fallback=os.path.splitext(task.dest_path)[1] or '.bin')
            # ensure dest_path has ext
            if not os.path.splitext(task.dest_path)[1]:
                task.dest_path += ext
            with open(task.dest_path, 'wb') as f:
                for chunk in r.iter_content(32768):
                    if task.cancel_event.is_set():
                        f.close()
                        try:
                            os.remove(task.dest_path)
                        except OSError:
                            pass
                        if task.callback_done:
                            task.callback_done(False, "Cancelled")
                        with self.lock:
                            self.tasks.pop(id(task), None)
                        return
                    if chunk:
                        f.write(chunk)
                        bytes_so_far += len(chunk)
                        if task.callback_progress:
                            elapsed = max(time.time() - started, 0.001)
                            speed = bytes_so_far / elapsed
                            task.callback_progress(bytes_so_far, total, speed)
            if task.callback_done:
                task.callback_done(True, task.dest_path)
            with self.lock:
                self.tasks.pop(id(task), None)
        else:
            with self.lock:
                self.tasks.pop(id(task), None)
            raise RuntimeError("No URL or file_id to download")

    def _download_google_drive(self, file_id, dest_path, progress_callback=None):
        """
        Reliable Google Drive download using gdown.
        """
        import gdown
        import os

        # Ensure destination has an extension
        if not os.path.splitext(dest_path)[1]:
            dest_path += ".zip"  # fallback

        # Build direct URL
        url = f"https://drive.google.com/uc?id={file_id}"

        # Download with gdown
        try:
            # Use gdown.download with quiet=False to see errors
            gdown.download(url, dest_path, quiet=False, use_cookies=False)
        except Exception as e:
            raise RuntimeError(f"gdown download failed for {file_id}: {e}")

        # Verify download
        if not os.path.exists(dest_path) or os.path.getsize(dest_path) < 1024:
            raise RuntimeError(f"Download failed, got HTML instead of file for {file_id}")

        # Optional progress callback (gdown doesn't natively support it reliably)
        if progress_callback:
            size = os.path.getsize(dest_path)
            progress_callback(size, size, 0)

        return dest_path



# single global manager
DOWNLOAD_MANAGER = DownloadManager()

def load_emulators_from_db(db_path):
        if not os.path.exists(db_path):
            return []

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(emulators)")
        cols = [r[1] for r in cur.fetchall()]

        select_cols = ["name","platform","cover","size","file_id","direct_url"]
        # only select columns that actually exist
        select_cols = [c for c in select_cols if c in cols]

        cur.execute(f"SELECT {','.join(select_cols)} FROM emulators")
        rows = cur.fetchall()
        emulators = []
        for r in rows:
            d = {}
            for idx, c in enumerate(select_cols):
                d[c] = r[idx] if idx < len(r) else ""
            # normalize keys to match UI code
            d["title"] = d.pop("name", "Unknown")
            d.setdefault("cover", "")
            d.setdefault("file_id", "")
            d.setdefault("direct_url", "")
            d.setdefault("size", "")
            d.setdefault("platform", "Unknown")
            emulators.append(d)
        conn.close()
        return emulators

# ---------- Data Loading ----------
def load_games_from_db(db_path=DB_PATH):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # discover columns
    cur.execute("PRAGMA table_info(games_metadata)")
    cols = [r[1] for r in cur.fetchall()]
    have_size = "size" in cols
    have_franchise = "franchise" in cols
    # build select accordingly
    select_cols = ["id","title","platform","description","cover","file_id","direct_url"]
    if have_size:
        select_cols.append("size")
    if have_franchise:
        select_cols.append("franchise")
    q = f"SELECT {','.join(select_cols)} FROM games_metadata"
    cur.execute(q)
    rows = cur.fetchall()
    games = []
    for r in rows:
        d = {}
        for idx, c in enumerate(select_cols):
            d[c] = r[idx] if idx < len(r) else ""
        # normalize
        d.setdefault("size", "")
        d.setdefault("franchise", "")
        games.append(d)
    conn.close()
    return games

# ---------- UI Classes ----------
class GameTile(ctk.CTkFrame):
    def __init__(self, parent, game, open_detail_callback, show_platform=False):
        super().__init__(parent, corner_radius=10, fg_color="#1e1e1e")
        self.game = game
        self.open_detail = open_detail_callback
        self.configure(width=TILE_SIZE[0], height=TILE_SIZE[1])

        # image
        img_path = os.path.join(COVERS_DIR, os.path.basename(game.get("cover") or ""))
        if os.path.exists(img_path):
            thumb = load_image_thumbnail(img_path, THUMB_DISPLAY)
        else:
            thumb = load_image_thumbnail(__file__, THUMB_DISPLAY)
        self.thumb_image = thumb
        self.img_label = ctk.CTkLabel(self, image=self.thumb_image, text="")
        self.img_label.pack(pady=(12,8))

        # title - bigger and bold
        self.title_label = ctk.CTkLabel(self, text=game["title"], wraplength=210, justify="center",
                                        font=ctk.CTkFont(size=13, weight="bold"))
        self.title_label.pack(padx=6)

        # show platform or description
        if show_platform:
            text = f"Platform: {game.get('platform','Unknown')}"
        else:
            text = (game.get("description") or "").strip().replace("\n"," ")
            if len(text) > 80: text = text[:77] + "..."
        self.desc_label = ctk.CTkLabel(self, text=text, wraplength=210, fg_color=None, text_color="#bdbdbd",
                                       font=ctk.CTkFont(size=10))
        self.desc_label.pack(padx=8, pady=(6,8))

        # click bindings
        for widget in (self, self.img_label, self.title_label, self.desc_label):
            widget.bind("<Button-1>", lambda e: self.open_detail(self.game))



class GameDetailDialog(ctk.CTkToplevel):
    def __init__(self, parent, game, download_dir_getter):
        super().__init__(parent)
        self.game = game
        self.download_dir_getter = download_dir_getter
        self.transient(parent)
        self.attributes("-topmost", True)
        self.lift()
        self.title(game["title"])
        self.geometry("1000x620")


        # LEFT SIDE (Cover, Platform, Size, Download button, Progress)
        left = ctk.CTkFrame(self, width=360, corner_radius=8)
        left.pack(side="left", fill="y", padx=12, pady=12)

        # COVER IMAGE
        img_path = os.path.join(COVERS_DIR, os.path.basename(game.get("cover") or ""))
        if os.path.exists(img_path):
            big_img = load_image_thumbnail(img_path, THUMB_SIZE)
        else:
            big_img = load_image_thumbnail(__file__, THUMB_SIZE)
        self.big_img = big_img
        self.cover_label = ctk.CTkLabel(left, image=self.big_img, text="")
        self.cover_label.pack(pady=(8, 10))

        # PLATFORM
        platform_lbl = ctk.CTkLabel(left, text=f"Platform: {game.get('platform', 'Unknown')}")
        platform_lbl.pack(pady=(4, 2))

        # SIZE
        size_val = game.get("size")
        if size_val:
            size_lbl = ctk.CTkLabel(left, text=f"Size: {size_val}")
            size_lbl.pack(pady=(2, 10))

        # DOWNLOAD BUTTON (moved UP here)
        self.btn_download = ctk.CTkButton(
            left,
            text="Download",
            command=self.start_download,
            width=200,
            height=40,
            fg_color="#2ECC71",
            hover_color="#27AE60",
            corner_radius=8
        )
        self.btn_download.pack(pady=(6, 14))

        # PROGRESS BARS CONTAINER
        self.progress_container = ctk.CTkFrame(left, fg_color="transparent")
        self.progress_container.pack(fill="x", padx=8, pady=(4, 8))

        # RIGHT SIDE (Title + Scrollable Description)
        right = ctk.CTkFrame(self, corner_radius=8)
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)

        # TITLE
        title_lbl = ctk.CTkLabel(right, text="  " + game["title"],
            font=ctk.CTkFont(size=22, weight="bold"))
        title_lbl.pack(anchor="nw", pady=(6, 8))

        # SCROLLABLE DESCRIPTION
        desc_text = game.get("description") or "No description available."
        desc_frame = ctk.CTkScrollableFrame(right)
        desc_frame.pack(fill="both", expand=True, pady=(4, 6))
        desc_lbl = ctk.CTkLabel(desc_frame, text=desc_text,
                                wraplength=520, justify="left")
        desc_lbl.pack(anchor="nw", padx=8, pady=8)

        # Track per-file progress bars
        self.file_progress_widgets = []
        self.file_speed_labels = []
        self.file_cancel_buttons = []
        self.active_tasks = []


    def start_download(self):
        raw = str(self.game.get("file_id") or "")
        if not raw or raw.strip() == "":
            messagebox.showwarning("No link", "No download link configured for this game.")
            return
        # parse file ids - accept | or comma
        parts = [p.strip() for p in re.split(r"[,\|]+", raw) if p.strip()]
        if not parts:
            messagebox.showwarning("No link", "No download link configured for this game.")
            return

        # Clear old progress UI
        for w in self.progress_container.winfo_children():
            w.destroy()
        self.file_progress_widgets = []
        self.file_speed_labels = []
        self.file_cancel_buttons = []
        self.active_tasks = []

        # create a row for each file
        single_file = (len(parts) == 1)

        for idx, fid in enumerate(parts):
            row = ctk.CTkFrame(self.progress_container)
            row.pack(fill="x", pady=(6,4))

            # Label: if 1 file → use game title, otherwise "Part X"
            if single_file:
                label_text = self.game["title"]
            else:
                label_text = f"Part {idx+1}"

            lbl = ctk.CTkLabel(row, text=label_text)
            lbl.pack(side="left", padx=(6,12))

            pb = ctk.CTkProgressBar(row, width=220)
            pb.set(0)
            pb.pack(side="left", padx=(0,8))
            self.file_progress_widgets.append(pb)

            speed_lbl = ctk.CTkLabel(row, text="0.0 MB/s", width=90)
            speed_lbl.pack(side="left", padx=(0,8))
            self.file_speed_labels.append(speed_lbl)

            # determine download directory (NO per-game folder)
            download_dir = self.download_dir_getter()
            os.makedirs(download_dir, exist_ok=True)

            safe_title = safe_filename(self.game["title"])
            single_file = (len(parts) == 1)

            # Determine filename: single file → just the game name
            if single_file:
                dest_name = safe_title
            else:
                dest_name = f"{safe_title}_part{idx+1}"

            dest_path = os.path.join(download_dir, dest_name)  # extension added later


            # find direct URL matching this file ID
            direct_url = str(self.game.get("direct_url") or "")
            url_for_task = None
            if direct_url:
                candidates = [u.strip() for u in re.split(r"[,\|]+", direct_url) if u.strip()]
                if idx < len(candidates):
                    url_for_task = candidates[idx]
                elif len(candidates) == 1:
                    url_for_task = candidates[0]

            # create the task
            task = DownloadTask(
                file_id=fid,
                url=url_for_task,
                dest_path=dest_path,
                callback_progress=lambda b, t, s, idx=idx: self._on_progress(idx, b, t, s),
                callback_done=lambda ok, path_or_error, idx=idx: self._on_done(idx, ok, path_or_error),
                index_in_game=idx
            )
            self.active_tasks.append(task)
            DOWNLOAD_MANAGER.enqueue(task)

            cancel_btn = ctk.CTkButton(
                row,
                text="Cancel",
                width=72,
                command=lambda t=task, i=idx: self._cancel_task(t, i)
            )
            cancel_btn.pack(side="left")
            self.file_cancel_buttons.append(cancel_btn)


    def _cancel_task(self, task, idx):
        DOWNLOAD_MANAGER.cancel_task(id(task))
        try:
            self.file_speed_labels[idx].configure(text="Cancelled")
            self.file_cancel_buttons[idx].configure(state="disabled")
        except Exception:
            pass

    def _on_progress(self, idx, bytes_dl, total, speed=0):
        try:
            pb = self.file_progress_widgets[idx]
            if total and total > 0:
                frac = bytes_dl/total
                pb.set(frac)
            else:
                # pulse if unknown size
                # simulate pulse: set to .5 then back (we'll use after)
                pb.set(0.5)
            self.file_speed_labels[idx].configure(text=f"{(speed/(1024*1024)):.1f} MB/s")
        except Exception:
            pass

    def _on_done(self, idx, ok, path_or_error):
        pb = self.file_progress_widgets[idx]
        if ok:
            pb.set(1.0)
            self.file_speed_labels[idx].configure(text="Done")
        else:
            if path_or_error == "Cancelled":
                self.file_speed_labels[idx].configure(text="Cancelled")
            else:
                self.file_speed_labels[idx].configure(text="Failed")
                messagebox.showerror("Download failed", f"Part {idx+1} failed:\n{path_or_error}")
        try:
            self.file_cancel_buttons[idx].configure(state="disabled")
        except Exception:
            pass

class MainApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Vixl0 eShop")
        self.geometry("1200x760")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        # app state
        try:
            self.games = load_games_from_db()
        except Exception as e:
            messagebox.showerror("DB error", str(e))
            self.destroy()
            return
        self.download_folder = DEFAULT_DOWNLOAD_DIR

        # top navigation (compact)
        top_frame = ctk.CTkFrame(self, height=48)
        top_frame.pack(fill="x", padx=12, pady=(12,6))
        self.btn_games = ctk.CTkButton(top_frame, text="Consoles", width=90, height=28, command=self.show_games)
        self.btn_games.pack(side="left", padx=(6,4), pady=6)
        self.btn_franchises = ctk.CTkButton(top_frame, text="Franchises", width=100, height=28, command=self.show_franchises)
        self.btn_franchises.pack(side="left", padx=4, pady=6)
        self.btn_emulators = ctk.CTkButton(top_frame, text="Emulators", width=90, height=28, command=self.show_emulators)
        self.btn_emulators.pack(side="left", padx=4, pady=6)
        self.btn_settings = ctk.CTkButton(top_frame, text="Settings", width=90, height=28, command=self.show_settings)
        self.btn_settings.pack(side="left", padx=4, pady=6)
        # a small spacer on right
        top_frame.pack_propagate(False)

        # console selector (compact horizontal row)
        console_frame = ctk.CTkFrame(self, height=56)
        console_frame.pack(fill="x", padx=12, pady=(0,12))
        self.console_scroll = ctk.CTkScrollableFrame(console_frame, orientation="horizontal", height=56)
        self.console_scroll.pack(fill="x", padx=8, pady=6)
        self.console_buttons = {}
        self.filter_mode = "console"
        self.populate_console_row()

        # main content: grid scroll area only (no left sidebar)
        content = ctk.CTkFrame(self)
        content.pack(fill="both", expand=True, padx=12, pady=(0,12))

        self.grid_scroll = ctk.CTkScrollableFrame(content)
        self.grid_scroll.pack(fill="both", expand=True, padx=6, pady=6)
        self.grid_frame = ctk.CTkFrame(self.grid_scroll)
        self.grid_frame.pack(padx=12, pady=12)

        # filter current console
        self.current_console = None
        DOWNLOAD_MANAGER.start()
        self.show_games()


    def show_emulators(self):
        # Clear current console selection
        self.current_console = None
        for w in self.grid_frame.winfo_children():
            w.destroy()

        emulators = load_emulators_from_db(os.path.join(APP_DIR, "emulators.db"))
        if not emulators:
            messagebox.showinfo("Info", "No emulators found in the database.")

        # Layout
        cols = 4
        row = col = 0
        for e in emulators:
            tile = GameTile(self.grid_frame, e, lambda game=e: self.open_emulator_detail(game), show_platform=True)
            tile.grid(row=row, column=col, padx=12, pady=12)
            col += 1
            if col >= cols:
                col = 0
                row += 1


    def open_emulator_detail(self, emulator):
        win = ctk.CTkToplevel(self)
        win.transient(self)
        win.attributes("-topmost", True)
        win.lift()
        win.title(emulator["title"])
        win.geometry("400x620")

        left = ctk.CTkFrame(win, width=300, corner_radius=8)
        left.pack(side="left", fill="y", padx=12, pady=12)

        img_path = os.path.join(COVERS_DIR, os.path.basename(emulator.get("cover") or ""))
        if os.path.exists(img_path):
            thumb = load_image_thumbnail(img_path, THUMB_SIZE)
        else:
            thumb = load_image_thumbnail(__file__, THUMB_SIZE)
        lbl_img = ctk.CTkLabel(left, image=thumb, text="")
        lbl_img.image = thumb
        lbl_img.pack(pady=(8, 12))

        lbl_title = ctk.CTkLabel(left, text=emulator["title"], font=ctk.CTkFont(size=16, weight="bold"))
        lbl_title.pack(pady=(6, 8))

        # Platform
        lbl_platform = ctk.CTkLabel(left, text=f"Platform: {emulator.get('platform','Unknown')}")
        lbl_platform.pack(pady=(2,2))

        # Size
        if emulator.get("size"):
            lbl_size = ctk.CTkLabel(left, text=f"Size: {emulator['size']}")
            lbl_size.pack(pady=(2,10))

        # Download button
        if emulator.get("file_id") or emulator.get("direct_url"):
            def start_download():
                raw = str(emulator.get("file_id") or "")
                if not raw.strip(): return
                # reuse same logic as GameDetailDialog.start_download
                # simplified: single file only
                download_dir = self.download_folder
                os.makedirs(download_dir, exist_ok=True)
                safe_title = safe_filename(emulator["title"])
                dest_path = os.path.join(download_dir, safe_title)
                direct_url = str(emulator.get("direct_url") or "")
                url_for_task = direct_url if direct_url else None
                task = DownloadTask(
                    file_id=raw,
                    url=url_for_task,
                    dest_path=dest_path,
                    callback_progress=None,
                    callback_done=lambda ok, p: messagebox.showinfo("Download","Download complete!" if ok else "Failed")
                )
                DOWNLOAD_MANAGER.enqueue(task)

            btn_download = ctk.CTkButton(left, text="Download", command=start_download,
                                        width=200, height=40, fg_color="#2ECC71", hover_color="#27AE60", corner_radius=8)
            btn_download.pack(pady=(6,14))

        # Description / info
        right = ctk.CTkFrame(win, corner_radius=8)
        right.pack(side="left", fill="both", expand=True, padx=12, pady=12)

        lbl_info = ctk.CTkLabel(right, text=(emulator.get("description") or "No description available."), wraplength=420, justify="left")
        lbl_info.pack(anchor="nw", padx=8, pady=8)



    def on_close(self):
        DOWNLOAD_MANAGER.stop()
        self.destroy()
        sys.exit(0)

    def populate_console_row(self):
        for w in self.console_scroll.winfo_children():
            w.destroy()
        self.console_buttons = {}
        if self.filter_mode == "console":
            values = sorted({(g.get('platform') or "Unknown") for g in self.games})
        else:
            values = sorted({(g.get('franchise') or "Unknown") for g in self.games})
        for p in values:
            btn = ctk.CTkButton(self.console_scroll, text=p, width=140, height=28, fg_color="#333333",
                                command=lambda p=p: self.filter_by_console(p))
            btn.pack(side="left", padx=6, pady=6)
            self.console_buttons[p] = btn

    def show_games(self):
        self.filter_mode = "console"
        self.populate_console_row()
        self.current_console = None
        self.render_grid()

    def show_franchises(self):
        self.filter_mode = "franchise"
        self.populate_console_row()
        self.current_console = None
        self.render_grid()


    def show_settings(self):
        # small settings window to change download folder and concurrency
        win = ctk.CTkToplevel(self)
        win.title("Settings")
        win.geometry("460x220")

        # Make it appear on top of the main window
        win.transient(self)          # Keep it associated with main window
        win.attributes("-topmost", True)
        win.grab_set()               # Optional: makes it modal (blocks interaction with main window)

        lbl = ctk.CTkLabel(win, text="Download folder", anchor="w")
        lbl.pack(fill="x", padx=12, pady=(12,6))
        path_lbl = ctk.CTkLabel(win, text=self.download_folder, anchor="w", wraplength=420)
        path_lbl.pack(fill="x", padx=12, pady=(0,8))

        def choose():
            d = filedialog.askdirectory(initialdir=self.download_folder)
            if d:
                self.download_folder = d
                path_lbl.configure(text=self.download_folder)
        btn = ctk.CTkButton(win, text="Choose download folder", command=choose)
        btn.pack(pady=(6,12))

        # concurrency control
        lbl2 = ctk.CTkLabel(win, text="Parallel downloads", anchor="w")
        lbl2.pack(fill="x", padx=12, pady=(6,6))
        var = ctk.StringVar(value=str(DOWNLOAD_MANAGER.concurrency))
        ent = ctk.CTkEntry(win, textvariable=var, width=80)
        ent.pack(padx=12, pady=(0,8))

        def apply_settings():
            try:
                v = int(var.get())
                if v < 1: raise ValueError()
            except Exception:
                messagebox.showerror("Invalid", "Enter a positive integer")
                return
            DOWNLOAD_MANAGER.concurrency = v
            messagebox.showinfo("Saved", "New concurrency will apply to new downloads.")

        btn2 = ctk.CTkButton(win, text="Apply", command=apply_settings)
        btn2.pack(pady=(6,12))


    def filter_by_console(self, platform):
        self.current_console = platform
        self.render_grid()

    def render_grid(self):
        # clear
        for w in self.grid_frame.winfo_children():
            w.destroy()
        # select games
        if self.current_console:
            if self.filter_mode == "console":
                display = [g for g in self.games if (g.get('platform') or "Unknown") == self.current_console]
            else:
                display = [g for g in self.games if (g.get('franchise') or "Unknown") == self.current_console]
        else:
            display = list(self.games)
        # layout: choose columns based on width; keep 4 by default
        cols = 4
        row = col = 0
        for g in display:
            tile = GameTile(self.grid_frame, g, lambda game=g: self.open_detail(game))
            tile.grid(row=row, column=col, padx=12, pady=12)
            col += 1
            if col >= cols:
                col = 0
                row += 1

    def open_detail(self, game):
        # pass getter for download folder so settings can change it
        d = GameDetailDialog(self, game, lambda: self.download_folder)
        d.grab_set()

# ---------- Run ----------
if __name__ == "__main__":
    # ensure covers folder exists
    os.makedirs(COVERS_DIR, exist_ok=True)
    app = MainApp()
    app.mainloop()
