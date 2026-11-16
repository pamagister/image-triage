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

function addProfileRow() {
  const body = document.querySelector(".profile-table tbody");
  if (!body) {
    return;
  }
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><input type="radio" name="selection_profile" value="new-profile" aria-label="Use new profile"></td>
    <td><input type="text" name="profile_name" value="new-profile" aria-label="Profile name"></td>
    <td><input class="compact-number" type="number" name="profile_top_n" min="0" max="5000" value="50"></td>
    <td><input class="compact-number" type="number" name="profile_diversity" min="0" max="1" step="0.05" value="0.5"></td>
    <td><input class="compact-number" type="number" name="profile_max_per_group" min="1" value="1"></td>
    <td><input class="compact-number" type="number" name="profile_max_per_day" min="0" value="5"></td>
    <td><input class="compact-number" type="number" name="profile_max_per_cluster" min="0" value="3"></td>
    <td><select name="profile_event_quota"><option value="sainte_lague">sainte_lague</option><option value="proportional">proportional</option><option value="equal">equal</option></select></td>
    <td><button type="button" class="button-danger compact-button" data-remove-profile>Remove</button></td>`;
  body.appendChild(row);
  row.querySelector("[data-remove-profile]").addEventListener("click", () => row.remove());
}

function addPresetRow() {
  const body = document.querySelector(".preset-table tbody");
  if (!body) {
    return;
  }
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><input type="checkbox" name="preset_enabled" value="new-preset" aria-label="Enable new preset"></td>
    <td><input type="text" name="preset_name" value="new-preset" aria-label="Preset name"></td>
    <td><input type="text" name="preset_label" value="New preset" aria-label="Preset label"></td>
    <td><input type="text" name="preset_overrides" value="{}" aria-label="Preset overrides"></td>
    <td><button type="button" class="button-danger compact-button" data-remove-preset>Remove</button></td>`;
  body.appendChild(row);
  row.querySelector("[data-remove-preset]").addEventListener("click", () => row.remove());
}

for (const button of document.querySelectorAll("[data-remove-profile]")) {
  button.addEventListener("click", () => button.closest("tr")?.remove());
}
for (const button of document.querySelectorAll("[data-remove-preset]")) {
  button.addEventListener("click", () => button.closest("tr")?.remove());
}
const addProfile = document.getElementById("add-profile");
if (addProfile) {
  addProfile.addEventListener("click", addProfileRow);
}
const addPreset = document.getElementById("add-preset");
if (addPreset) {
  addPreset.addEventListener("click", addPresetRow);
}
