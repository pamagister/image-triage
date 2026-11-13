"use strict";

const form = document.getElementById("settings-form");
const newRootInput = document.getElementById("new-root");
const browseButton = document.getElementById("browse-root");
const dialog = document.getElementById("browse-dialog");
const browseList = document.getElementById("browse-list");
const browseCurrent = document.getElementById("browse-current");
const browseError = document.getElementById("browse-error");
const browseUp = document.getElementById("browse-up");
const browseSelect = document.getElementById("browse-select");
const browseClose = document.getElementById("browse-close");
const browseCancel = document.getElementById("browse-cancel");

let currentPath = "";

for (const button of document.querySelectorAll("[data-remove-root]")) {
  button.addEventListener("click", () => {
    const path = button.dataset.removeRoot;
    if (!window.confirm(button.dataset.confirm || `Remove ${path}?`)) {
      return;
    }
    const field = document.createElement("input");
    field.type = "hidden";
    field.name = "remove_root";
    field.value = path;
    form.appendChild(field);
    form.requestSubmit();
  });
}

function setBrowseError(message) {
  browseError.textContent = message;
  browseError.hidden = !message;
}

function renderDirectories(directories) {
  browseList.replaceChildren();
  if (!directories.length) {
    const empty = document.createElement("li");
    empty.className = "browse-empty";
    empty.textContent = "No subdirectories.";
    browseList.appendChild(empty);
    return;
  }
  for (const directory of directories) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "browse-directory";
    button.dataset.path = directory.path;
    button.textContent = directory.name;
    button.addEventListener("click", () => loadDirectory(directory.path));
    item.appendChild(button);
    browseList.appendChild(item);
  }
}

async function loadDirectory(path) {
  setBrowseError("");
  try {
    const response = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "cannot read directory");
    }
    currentPath = payload.path;
    browseCurrent.textContent = currentPath;
    browseUp.disabled = !payload.parent;
    browseUp.dataset.path = payload.parent || "";
    renderDirectories(payload.directories);
  } catch (error) {
    setBrowseError(error.message);
  }
}

browseButton.addEventListener("click", () => {
  const initial = newRootInput.value.trim() || "~";
  dialog.showModal();
  loadDirectory(initial);
});

browseUp.addEventListener("click", () => {
  if (browseUp.dataset.path) {
    loadDirectory(browseUp.dataset.path);
  }
});

browseSelect.addEventListener("click", () => {
  if (!currentPath) {
    return;
  }
  newRootInput.value = currentPath;
  dialog.close();
  newRootInput.focus();
});

browseClose.addEventListener("click", () => dialog.close());
browseCancel.addEventListener("click", () => dialog.close());