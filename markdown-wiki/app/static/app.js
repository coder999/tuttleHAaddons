const fileListEl = document.getElementById("file-list");
const contentEl = document.getElementById("content");
const refreshBtn = document.getElementById("refresh-btn");

let files = [];
let activeFilename = null;

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showMessage(message, className = "notice") {
  contentEl.innerHTML = `<p class="${className}">${escapeHtml(message)}</p>`;
}

function findInitialFile(availableFiles) {
  const hashFile = decodeURIComponent(window.location.hash.replace(/^#/, ""));
  if (hashFile && availableFiles.some((f) => f.filename === hashFile)) {
    return hashFile;
  }

  if (availableFiles.some((f) => f.filename === "Home.md")) {
    return "Home.md";
  }

  return availableFiles.length > 0 ? availableFiles[0].filename : null;
}

function setActiveInSidebar(filename) {
  activeFilename = filename;
  const buttons = fileListEl.querySelectorAll("button[data-filename]");
  for (const button of buttons) {
    if (button.dataset.filename === filename) {
      button.classList.add("active");
    } else {
      button.classList.remove("active");
    }
  }
}

function renderSidebar() {
  fileListEl.innerHTML = "";

  for (const file of files) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.filename = file.filename;
    button.textContent = file.title;
    button.addEventListener("click", () => {
      loadPage(file.filename, true);
    });

    li.appendChild(button);
    fileListEl.appendChild(li);
  }

  if (activeFilename) {
    setActiveInSidebar(activeFilename);
  }
}

async function fetchFiles() {
  const response = await fetch("api/files", { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Failed to fetch file list");
  }
  return response.json();
}

async function loadPage(filename, updateHash = false) {
  if (!filename) {
    showMessage("No page selected.");
    return;
  }

  setActiveInSidebar(filename);
  showMessage("Loading page...");

  try {
    const response = await fetch(`api/page/${encodeURIComponent(filename)}`, {
      cache: "no-store",
    });

    if (!response.ok) {
      const errorPayload = await response.json().catch(() => ({}));
      throw new Error(errorPayload.error || "Failed to load page");
    }

    const payload = await response.json();
    contentEl.innerHTML = payload.html;
    if (updateHash || window.location.hash.replace(/^#/, "") !== payload.filename) {
      window.location.hash = encodeURIComponent(payload.filename);
    }

    setActiveInSidebar(payload.filename);
    document.title = `${payload.title} - Markdown Wiki`;
  } catch (error) {
    showMessage(error.message || "Failed to load page", "error");
  }
}

async function refreshAndLoadInitial() {
  showMessage("Loading files...");

  try {
    files = await fetchFiles();
    renderSidebar();

    if (!files.length) {
      showMessage("No Markdown files found in /share/wiki.");
      return;
    }

    const initial = findInitialFile(files);
    await loadPage(initial, false);
  } catch (error) {
    showMessage(error.message || "Failed to load file list", "error");
  }
}

refreshBtn.addEventListener("click", async () => {
  const previous = activeFilename;

  try {
    files = await fetchFiles();
    renderSidebar();

    if (!files.length) {
      activeFilename = null;
      showMessage("No Markdown files found in /share/wiki.");
      return;
    }

    const hashFile = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    const candidates = [hashFile, previous, findInitialFile(files)].filter(Boolean);
    const target = candidates.find((name) => files.some((f) => f.filename === name));
    await loadPage(target || files[0].filename, false);
  } catch (error) {
    showMessage(error.message || "Refresh failed", "error");
  }
});

window.addEventListener("hashchange", () => {
  const hashFile = decodeURIComponent(window.location.hash.replace(/^#/, ""));
  if (hashFile && files.some((f) => f.filename === hashFile) && hashFile !== activeFilename) {
    loadPage(hashFile, false);
  }
});

refreshAndLoadInitial();
