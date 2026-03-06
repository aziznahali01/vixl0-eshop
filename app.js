const FALLBACK_SAMPLE = [
  { id: 1, title: "Super Mario 64", console: "Nintendo 64", franchise: "Mario", description: "Classic 3D platforming adventure.", size: "8 MB", cover: "covers/super_mario_64.png", driveFileId: "", directUrl: "" }
];

let games = [];
let filteredGames = [];
let renderedCount = 0;
const PAGE_SIZE = 72;

let currentView = "consoles";
let currentFilter = "All";
let searchText = "";

let settings = {
  downloadFolder: "E:\\Games",
  maxDownloads: 2,
  theme: "dark"
};

let latestDownloadState = {
  active: [],
  queue: [],
  history: []
};

const elements = {
  tabs: [...document.querySelectorAll(".tab")],
  filters: document.getElementById("filtersSection"),
  library: document.getElementById("librarySection"),
  settingsSection: document.getElementById("settingsSection"),
  stats: document.getElementById("stats"),
  grid: document.getElementById("gameGrid"),
  sentinel: document.getElementById("gridSentinel"),
  search: document.getElementById("searchInput"),
  detailsDialog: document.getElementById("detailsDialog"),
  detailsContent: document.getElementById("detailsContent"),
  cardTemplate: document.getElementById("cardTemplate"),
  downloadTemplate: document.getElementById("downloadItemTemplate"),
  downloadList: document.getElementById("downloadList"),
  dmCounters: document.getElementById("dmCounters"),
  downloadFolder: document.getElementById("downloadFolder"),
  chooseFolder: document.getElementById("chooseFolder"),
  maxDownloads: document.getElementById("maxDownloads"),
  themeSelect: document.getElementById("themeSelect"),
  saveSettings: document.getElementById("saveSettings"),
  clearCache: document.getElementById("clearCache")
};

bootstrap();

async function bootstrap() {
  bindEvents();

  if (window.electronAPI) {
    settings = await window.electronAPI.getSettings();
    games = await window.electronAPI.getGames();
    latestDownloadState = await window.electronAPI.getDownloadState();
    window.electronAPI.onDownloadState((state) => {
      latestDownloadState = state;
      renderDownloadManager();
    });
  } else {
    games = buildLargeLibrary(FALLBACK_SAMPLE, 2000);
  }

  if (!Array.isArray(games) || games.length === 0) {
    games = buildLargeLibrary(FALLBACK_SAMPLE, 300);
  }

  applyTheme(settings.theme);
  hydrateSettingsUI();
  renderFilters();
  refilterAndRender(true);
  setupInfiniteScroll();
  renderDownloadManager();
}

function buildLargeLibrary(seed, total) {
  const consoles = ["NES", "SNES", "Nintendo 64", "GameCube", "Wii", "Nintendo 3DS", "Nintendo DS", "PlayStation", "PSP", "Xbox"];
  const franchises = ["Mario", "Zelda", "Pokemon", "Kirby", "Sonic", "Persona", "Crash", "Donkey Kong"];
  const out = [];
  for (let i = 0; i < total; i += 1) {
    const base = seed[i % seed.length];
    out.push({
      ...base,
      id: i + 1,
      title: i < seed.length ? base.title : `${base.title} (${i + 1})`,
      console: base.console || consoles[i % consoles.length],
      franchise: base.franchise || franchises[i % franchises.length]
    });
  }
  return out;
}

function bindEvents() {
  elements.tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      elements.tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      currentView = tab.dataset.view;
      currentFilter = "All";
      elements.settingsSection.classList.toggle("hidden", currentView !== "settings");
      elements.library.classList.toggle("hidden", currentView === "settings");
      elements.filters.classList.toggle("hidden", currentView === "settings");
      if (currentView !== "settings") {
        renderFilters();
        refilterAndRender(true);
      }
    });
  });

  elements.search.addEventListener("input", (e) => {
    searchText = e.target.value.trim().toLowerCase();
    refilterAndRender(true);
  });

  elements.saveSettings.addEventListener("click", async () => {
    const next = {
      downloadFolder: elements.downloadFolder.value.trim() || settings.downloadFolder,
      maxDownloads: Math.max(1, Math.min(10, Number(elements.maxDownloads.value) || settings.maxDownloads || 2)),
      theme: elements.themeSelect.value === "light" ? "light" : "dark"
    };

    if (window.electronAPI) {
      settings = await window.electronAPI.saveSettings(next);
    } else {
      settings = next;
    }
    applyTheme(settings.theme);
    hydrateSettingsUI();
    renderDownloadManager();
  });

  elements.clearCache.addEventListener("click", async () => {
    const reset = {
      downloadFolder: "E:\\Games",
      maxDownloads: 2,
      theme: "dark"
    };

    if (window.electronAPI) {
      settings = await window.electronAPI.saveSettings(reset);
    } else {
      settings = reset;
    }
    applyTheme(settings.theme);
    hydrateSettingsUI();
  });

  elements.chooseFolder.addEventListener("click", async () => {
    if (!window.electronAPI) return;
    const selected = await window.electronAPI.chooseFolder();
    if (selected) elements.downloadFolder.value = selected;
  });

  elements.detailsDialog.addEventListener("click", (e) => {
    const rect = elements.detailsDialog.getBoundingClientRect();
    const inDialog = rect.top <= e.clientY && e.clientY <= rect.top + rect.height
      && rect.left <= e.clientX && e.clientX <= rect.left + rect.width;
    if (!inDialog) elements.detailsDialog.close();
  });
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

function hydrateSettingsUI() {
  elements.downloadFolder.value = settings.downloadFolder || "E:\\Games";
  elements.maxDownloads.value = settings.maxDownloads || 2;
  elements.themeSelect.value = settings.theme || "dark";
}

function getFilterValues() {
  if (currentView === "franchises") {
    return ["All", ...new Set(games.map((g) => g.franchise || "Other").sort())];
  }
  return ["All", ...new Set(games.map((g) => g.console || "Unknown").sort())];
}

function renderFilters() {
  const values = getFilterValues();
  elements.filters.innerHTML = "";
  values.forEach((value) => {
    const chip = document.createElement("button");
    chip.className = `chip ${value === currentFilter ? "active" : ""}`;
    chip.textContent = value;
    chip.addEventListener("click", () => {
      currentFilter = value;
      renderFilters();
      refilterAndRender(true);
    });
    elements.filters.appendChild(chip);
  });
}

function refilterAndRender(reset) {
  filteredGames = games.filter((game) => {
    const franchise = game.franchise || "Other";
    const consoleName = game.console || "Unknown";
    const viewMatch = currentFilter === "All"
      || (currentView === "franchises" ? franchise === currentFilter : consoleName === currentFilter);

    const textMatch = !searchText
      || String(game.title || "").toLowerCase().includes(searchText)
      || String(consoleName).toLowerCase().includes(searchText)
      || String(franchise).toLowerCase().includes(searchText);

    return viewMatch && textMatch;
  });

  elements.stats.textContent = `${filteredGames.length.toLocaleString()} games`;

  if (reset) {
    renderedCount = 0;
    elements.grid.innerHTML = "";
  }
  renderNextPage();
}

function renderNextPage() {
  const max = Math.min(filteredGames.length, renderedCount + PAGE_SIZE);
  for (let i = renderedCount; i < max; i += 1) {
    const game = filteredGames[i];
    elements.grid.appendChild(createCard(game));
  }
  renderedCount = max;
  observeLazyImages();
}

function setupInfiniteScroll() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting && renderedCount < filteredGames.length) renderNextPage();
    });
  }, { rootMargin: "320px" });
  observer.observe(elements.sentinel);
}

function createCard(game) {
  const node = elements.cardTemplate.content.firstElementChild.cloneNode(true);
  const img = node.querySelector(".cover");
  node.querySelector(".title").textContent = game.title || "Unknown";
  node.querySelector(".meta").textContent = `${game.console || "Unknown"} | ${game.franchise || "Other"}`;
  node.querySelector(".size").textContent = `Size: ${game.size || "Unknown"}`;

  if (game.cover && isAbsolutePath(game.cover)) {
    img.dataset.src = pathToFileURL(game.cover);
  } else {
    img.dataset.src = game.cover || "";
  }
  img.alt = `${game.title || "Game"} cover`;

  node.querySelector(".btn-details").addEventListener("click", () => openDetails(game));
  node.querySelector(".btn-download").addEventListener("click", () => enqueueDownload(game));
  return node;
}

const imageObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    const img = entry.target;
    img.src = img.dataset.src;
    img.onerror = () => {
      img.src = "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400'><rect width='100%' height='100%' fill='#111'/><text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle' fill='#777' font-size='20'>No Cover</text></svg>`);
    };
    imageObserver.unobserve(img);
  });
}, { rootMargin: "280px" });

function observeLazyImages() {
  document.querySelectorAll("img.lazy[data-src]").forEach((img) => imageObserver.observe(img));
}

function openDetails(game) {
  const url = game.directUrl || (game.driveFileId ? `https://drive.google.com/uc?export=download&id=${encodeURIComponent(game.driveFileId)}` : "No link");
  const cover = game.cover && isAbsolutePath(game.cover) ? pathToFileURL(game.cover) : (game.cover || "");

  elements.detailsContent.innerHTML = `
    <div>
      <img class="details-cover" src="${escapeHtml(cover)}" alt="${escapeHtml(game.title || "Game")} cover" />
    </div>
    <div class="details-right">
      <h3>${escapeHtml(game.title || "Unknown")}</h3>
      <p><strong>Console:</strong> ${escapeHtml(game.console || "Unknown")}</p>
      <p><strong>Franchise:</strong> ${escapeHtml(game.franchise || "Other")}</p>
      <p><strong>File Size:</strong> ${escapeHtml(game.size || "Unknown")}</p>
      <p>${escapeHtml(game.description || "No description available.")}</p>
      <p><strong>Source:</strong> ${url === "No link" ? "No link" : `<a href="${escapeHtml(url)}" target="_blank">Download URL</a>`}</p>
      <div class="details-actions">
        <button id="detailsDownload" class="btn-primary">Download</button>
        <button id="detailsClose" class="btn-secondary">Close</button>
      </div>
    </div>
  `;

  const image = elements.detailsContent.querySelector(".details-cover");
  image.onerror = () => {
    image.src = "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400'><rect width='100%' height='100%' fill='#111'/><text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle' fill='#777' font-size='20'>No Cover</text></svg>`);
  };

  elements.detailsDialog.showModal();

  document.getElementById("detailsClose").addEventListener("click", () => elements.detailsDialog.close());
  document.getElementById("detailsDownload").addEventListener("click", () => {
    enqueueDownload(game);
    elements.detailsDialog.close();
  });
}

async function enqueueDownload(game) {
  if (!window.electronAPI) return;
  await window.electronAPI.enqueueDownload(game);
}

async function cancelTask(taskId) {
  if (!window.electronAPI) return;
  await window.electronAPI.cancelDownload(taskId);
}

function renderDownloadManager() {
  const all = [...(latestDownloadState.active || []), ...(latestDownloadState.queue || []), ...(latestDownloadState.history || []).slice(0, 10)];
  elements.downloadList.innerHTML = "";

  all.forEach((task) => {
    const item = elements.downloadTemplate.content.firstElementChild.cloneNode(true);
    item.querySelector(".name").textContent = task.gameTitle;
    item.querySelector(".status").textContent = task.status;
    item.querySelector(".progress-bar").style.width = `${Math.max(0, Math.min(100, task.progress || 0))}%`;

    const speedText = task.status === "Downloading"
      ? `${(task.speedMbps || 0).toFixed(2)} MB/s`
      : `${(task.progress || 0).toFixed(0)}%`;
    item.querySelector(".speed").textContent = speedText;

    const pathEl = item.querySelector(".path");
    pathEl.textContent = task.destPath ? task.destPath : "";

    const errEl = item.querySelector(".error");
    errEl.textContent = task.error ? task.error : "";

    const cancelButton = item.querySelector(".btn-cancel");
    const cancellable = task.status === "Queued" || task.status === "Downloading";
    cancelButton.disabled = !cancellable;
    cancelButton.addEventListener("click", () => cancelTask(task.id));

    elements.downloadList.appendChild(item);
  });

  const activeCount = (latestDownloadState.active || []).length;
  const queueCount = (latestDownloadState.queue || []).length;
  elements.dmCounters.textContent = `${activeCount} active | ${queueCount} queued | ${settings.downloadFolder || ""}`;
}

function isAbsolutePath(value) {
  return /^[a-zA-Z]:\\/.test(String(value || ""));
}

function pathToFileURL(winPath) {
  const normalized = String(winPath).replace(/\\/g, "/");
  return `file:///${encodeURI(normalized)}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
