const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const https = require("https");
const { spawn } = require("child_process");

const APP_ROOT = __dirname;
const DB_PATH = path.join(APP_ROOT, "games.db");
const COVERS_DIR = path.join(APP_ROOT, "covers");
const GAMES_JSON_PATH = path.join(APP_ROOT, "data", "games.json");

const downloadState = {
  queue: [],
  active: new Map(),
  history: []
};

let settings = {
  downloadFolder: path.join(process.env.USERPROFILE || app.getPath("downloads"), "Downloads"),
  maxDownloads: 2,
  theme: "dark"
};

const taskRuntime = new Map();

function safeFilename(name) {
  return String(name || "file")
    .toLowerCase()
    .replace(/[<>:"/\\|?*]/g, "")
    .replace(/[^\w\s'-]/g, "")
    .trim()
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_") || "file";
}

function inferExtensionFromContentType(contentType) {
  const ct = String(contentType || "").toLowerCase();
  if (ct.includes("application/zip")) return ".zip";
  if (ct.includes("application/x-7z-compressed")) return ".7z";
  if (ct.includes("application/x-rar-compressed") || ct.includes("application/vnd.rar")) return ".rar";
  if (ct.includes("application/x-iso9660-image")) return ".iso";
  if (ct.includes("application/x-cd-image")) return ".iso";
  if (ct.includes("application/x-chd")) return ".chd";
  if (ct.includes("application/octet-stream")) return "";
  return "";
}

function extractFilenameFromContentDisposition(contentDisposition) {
  const cd = String(contentDisposition || "");
  if (!cd) return "";

  const utf8Match = cd.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return path.basename(decodeURIComponent(utf8Match[1].trim().replace(/^"|"$/g, "")));
    } catch (_) {
      return path.basename(utf8Match[1].trim().replace(/^"|"$/g, ""));
    }
  }

  const plainMatch = cd.match(/filename\s*=\s*("?)([^";]+)\1/i);
  if (plainMatch && plainMatch[2]) {
    return path.basename(plainMatch[2].trim());
  }
  return "";
}

function extensionFromUrl(rawUrl) {
  try {
    const u = new URL(rawUrl);
    const ext = path.extname(path.basename(u.pathname || ""));
    if (!ext) return "";
    if (ext.length > 10) return "";
    return ext.toLowerCase();
  } catch (_) {
    return "";
  }
}

function chooseDownloadFilename(gameTitle, url, headers) {
  const fromHeader = extractFilenameFromContentDisposition(headers?.["content-disposition"]);
  if (fromHeader) {
    const ext = path.extname(fromHeader).toLowerCase();
    const base = path.basename(fromHeader, ext);
    if (ext) return `${safeFilename(base)}${ext}`;
  }

  const fromUrlExt = extensionFromUrl(url);
  const fromCtExt = inferExtensionFromContentType(headers?.["content-type"]);
  const ext = fromUrlExt || fromCtExt || ".zip";
  return `${safeFilename(gameTitle)}${ext}`;
}

function getUniquePath(dir, filename) {
  const ext = path.extname(filename);
  const base = path.basename(filename, ext);
  let candidate = path.join(dir, filename);
  let counter = 1;
  while (fs.existsSync(candidate) || fs.existsSync(`${candidate}.part`)) {
    candidate = path.join(dir, `${base}_${counter}${ext}`);
    counter += 1;
  }
  return candidate;
}

function settingsPath() {
  return path.join(app.getPath("userData"), "settings.json");
}

function loadSettings() {
  try {
    const raw = fs.readFileSync(settingsPath(), "utf8");
    settings = { ...settings, ...JSON.parse(raw) };
  } catch (_) {}
}

function saveSettings() {
  fs.mkdirSync(path.dirname(settingsPath()), { recursive: true });
  fs.writeFileSync(settingsPath(), JSON.stringify(settings, null, 2), "utf8");
}

function broadcastDownloadState() {
  const payload = serializeDownloadState();
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send("downloads:state", payload);
  });
}

function serializeDownloadState() {
  return {
    queue: downloadState.queue.map(publicTask),
    active: Array.from(downloadState.active.values()).map(publicTask),
    history: downloadState.history.map(publicTask)
  };
}

function publicTask(task) {
  return {
    id: task.id,
    gameTitle: task.gameTitle,
    status: task.status,
    progress: task.progress,
    speedMbps: task.speedMbps,
    downloadedBytes: task.downloadedBytes,
    totalBytes: task.totalBytes,
    destPath: task.destPath,
    error: task.error || ""
  };
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 720,
    backgroundColor: "#090c12",
    webPreferences: {
      preload: path.join(APP_ROOT, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  win.loadFile(path.join(APP_ROOT, "index.html"));
}

function runPythonQuery(sql) {
  return new Promise((resolve, reject) => {
    const pyCode = [
      "import sqlite3, json, sys",
      "db_path = sys.argv[1]",
      "query = sys.argv[2]",
      "conn = sqlite3.connect(db_path)",
      "conn.row_factory = sqlite3.Row",
      "cur = conn.cursor()",
      "rows = [dict(r) for r in cur.execute(query).fetchall()]",
      "conn.close()",
      "payload = json.dumps(rows, ensure_ascii=False)",
      "sys.stdout.buffer.write(payload.encode('utf-8'))"
    ].join("; ");

    const child = spawn("python", ["-c", pyCode, DB_PATH, sql], {
      cwd: APP_ROOT,
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONIOENCODING: "utf-8",
        PYTHONUTF8: "1"
      }
    });

    let out = "";
    let err = "";
    child.stdout.on("data", (d) => { out += d.toString(); });
    child.stderr.on("data", (d) => { err += d.toString(); });
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(err || `Python exited ${code}`));
        return;
      }
      try {
        resolve(JSON.parse(out || "[]"));
      } catch (e) {
        reject(e);
      }
    });
  });
}

async function loadGamesFromDb() {
  if (fs.existsSync(GAMES_JSON_PATH)) {
    const raw = fs.readFileSync(GAMES_JSON_PATH, "utf8");
    const fromJson = JSON.parse(raw);
    return fromJson.map((r) => ({
      id: r.id,
      title: r.title || "Unknown",
      console: r.console || "Unknown",
      franchise: r.franchise || inferFranchise(r.title || ""),
      description: r.description || "No description available.",
      size: r.size || "Unknown",
      cover: normalizeCoverPath(r.cover),
      driveFileId: r.driveFileId || "",
      directUrl: r.directUrl || ""
    }));
  }

  if (!fs.existsSync(DB_PATH)) return [];
  const rows = await runPythonQuery("SELECT id,title,platform,description,size,cover,file_id,direct_url FROM games_metadata");
  return rows.map((r) => ({
    id: r.id,
    title: r.title || "Unknown",
    console: r.platform || "Unknown",
    franchise: inferFranchise(r.title || ""),
    description: r.description || "No description available.",
    size: r.size || "Unknown",
    cover: normalizeCoverPath(r.cover),
    driveFileId: (r.file_id || "").split(/[|,]/).map((x) => x.trim()).filter(Boolean)[0] || "",
    directUrl: (r.direct_url || "").split(/[|,]/).map((x) => x.trim()).filter(Boolean)[0] || ""
  }));
}

function normalizeCoverPath(rawPath) {
  if (!rawPath) return "";
  const basename = path.basename(String(rawPath));
  const candidate = path.join(COVERS_DIR, basename);
  return fs.existsSync(candidate) ? candidate : "";
}

function inferFranchise(title) {
  const t = String(title).toLowerCase();
  if (t.includes("mario") || t.includes("luigi")) return "Mario";
  if (t.includes("zelda")) return "Zelda";
  if (t.includes("pokemon") || t.includes("pokémon")) return "Pokemon";
  if (t.includes("kirby")) return "Kirby";
  if (t.includes("sonic")) return "Sonic";
  if (t.includes("persona")) return "Persona";
  if (t.includes("crash")) return "Crash";
  if (t.includes("donkey kong") || t.includes("diddy kong")) return "Donkey Kong";
  return "Other";
}

function enqueueDownload(game) {
  const id = `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
  const task = {
    id,
    gameTitle: game.title,
    fileId: game.driveFileId || "",
    directUrl: game.directUrl || "",
    status: "Queued",
    progress: 0,
    speedMbps: 0,
    downloadedBytes: 0,
    totalBytes: 0,
    destPath: "",
    error: ""
  };
  downloadState.queue.push(task);
  pumpQueue();
  broadcastDownloadState();
  return id;
}

function cancelTask(taskId) {
  const idx = downloadState.queue.findIndex((t) => t.id === taskId);
  if (idx >= 0) {
    const task = downloadState.queue.splice(idx, 1)[0];
    task.status = "Cancelled";
    downloadState.history.unshift(task);
    trimHistory();
    broadcastDownloadState();
    return true;
  }

  const activeTask = downloadState.active.get(taskId);
  if (!activeTask) return false;

  activeTask.status = "Cancelled";
  const rt = taskRuntime.get(taskId);
  if (rt?.req) rt.req.destroy(new Error("Cancelled"));
  if (rt?.stream) rt.stream.destroy(new Error("Cancelled"));
  if (rt?.tmpPath) {
    fs.rm(rt.tmpPath, { force: true }, () => {});
  }
  return true;
}

function pumpQueue() {
  while (downloadState.active.size < settings.maxDownloads && downloadState.queue.length > 0) {
    const task = downloadState.queue.shift();
    task.status = "Downloading";
    downloadState.active.set(task.id, task);
    startTaskDownload(task).finally(() => {
      downloadState.active.delete(task.id);
      downloadState.history.unshift(task);
      trimHistory();
      taskRuntime.delete(task.id);
      broadcastDownloadState();
      pumpQueue();
    });
  }
}

function trimHistory() {
  if (downloadState.history.length > 100) downloadState.history.length = 100;
}

function startTaskDownload(task) {
  return new Promise((resolve) => {
    const url = task.directUrl || (task.fileId ? `https://drive.google.com/uc?export=download&id=${encodeURIComponent(task.fileId)}` : "");
    if (!url) {
      task.status = "Failed";
      task.error = "No download URL or file ID";
      resolve();
      return;
    }

    fs.mkdirSync(settings.downloadFolder, { recursive: true });
    let finalPath = "";
    let tmpPath = "";

    const startedAt = Date.now();

    const follow = (currentUrl, redirectsLeft = 5) => {
      if (redirectsLeft < 0) {
        task.status = "Failed";
        task.error = "Too many redirects";
        resolve();
        return;
      }

      const mod = currentUrl.startsWith("https:") ? https : http;
      const req = mod.get(currentUrl, {
        headers: {
          "User-Agent": "Mozilla/5.0 Vixl0-eShop/1.0"
        }
      }, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          const nextUrl = new URL(res.headers.location, currentUrl).toString();
          res.resume();
          follow(nextUrl, redirectsLeft - 1);
          return;
        }

        if (res.statusCode !== 200) {
          task.status = "Failed";
          task.error = `HTTP ${res.statusCode}`;
          res.resume();
          resolve();
          return;
        }

        task.totalBytes = Number(res.headers["content-length"] || 0);

        const decidedFilename = chooseDownloadFilename(task.gameTitle, currentUrl, res.headers);
        finalPath = getUniquePath(settings.downloadFolder, decidedFilename);
        tmpPath = `${finalPath}.part`;
        task.destPath = finalPath;

        const stream = fs.createWriteStream(tmpPath);
        taskRuntime.set(task.id, { req, stream, tmpPath });

        res.on("data", (chunk) => {
          task.downloadedBytes += chunk.length;
          if (task.totalBytes > 0) {
            task.progress = Math.min(100, (task.downloadedBytes / task.totalBytes) * 100);
          }
          const elapsedSec = Math.max((Date.now() - startedAt) / 1000, 0.001);
          const speedBytesSec = task.downloadedBytes / elapsedSec;
          task.speedMbps = speedBytesSec / (1024 * 1024);
          broadcastDownloadState();
        });

        res.pipe(stream);

        stream.on("finish", () => {
          stream.close(() => {
            if (task.status === "Cancelled") {
              fs.rm(tmpPath, { force: true }, () => resolve());
              return;
            }
            fs.rename(tmpPath, finalPath, (err) => {
              if (err) {
                task.status = "Failed";
                task.error = String(err.message || err);
              } else {
                task.status = "Completed";
                task.progress = 100;
                task.speedMbps = 0;
              }
              resolve();
            });
          });
        });

        const fail = (e) => {
          if (task.status === "Cancelled") {
            task.speedMbps = 0;
          } else {
            task.status = "Failed";
            task.error = String(e?.message || e || "Download error");
          }
          if (tmpPath) {
            fs.rm(tmpPath, { force: true }, () => resolve());
          } else {
            resolve();
          }
        };

        req.on("error", fail);
        res.on("error", fail);
        stream.on("error", fail);
      });

      req.on("error", (e) => {
        if (task.status === "Cancelled") {
          task.speedMbps = 0;
        } else {
          task.status = "Failed";
          task.error = String(e?.message || e || "Request error");
        }
        resolve();
      });

      taskRuntime.set(task.id, { req, tmpPath });
    };

    follow(url);
  });
}

function registerIpc() {
  ipcMain.handle("app:getGames", async () => {
    return loadGamesFromDb();
  });

  ipcMain.handle("settings:get", async () => settings);

  ipcMain.handle("settings:save", async (_event, incoming) => {
    settings = {
      ...settings,
      downloadFolder: incoming.downloadFolder || settings.downloadFolder,
      maxDownloads: Math.max(1, Math.min(10, Number(incoming.maxDownloads) || settings.maxDownloads)),
      theme: incoming.theme === "light" ? "light" : "dark"
    };
    saveSettings();
    pumpQueue();
    broadcastDownloadState();
    return settings;
  });

  ipcMain.handle("settings:chooseFolder", async () => {
    const result = await dialog.showOpenDialog({ properties: ["openDirectory", "createDirectory"] });
    if (result.canceled || !result.filePaths.length) return null;
    return result.filePaths[0];
  });

  ipcMain.handle("downloads:enqueue", async (_event, game) => enqueueDownload(game));
  ipcMain.handle("downloads:cancel", async (_event, taskId) => cancelTask(taskId));
  ipcMain.handle("downloads:getState", async () => serializeDownloadState());
}

app.whenReady().then(() => {
  loadSettings();
  registerIpc();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

