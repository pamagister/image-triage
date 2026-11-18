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

function moveRow(button, offset) {
  const row = button.closest("[data-profile-row], [data-preset-row]");
  if (!row) {
    return;
  }
  const sibling =
    offset < 0 ? row.previousElementSibling : row.nextElementSibling;
  if (sibling) {
    row.parentElement.insertBefore(offset < 0 ? row : sibling, offset < 0 ? sibling : row);
  }
}

for (const button of document.querySelectorAll("[data-move-up]")) {
  button.addEventListener("click", () => moveRow(button, -1));
}
for (const button of document.querySelectorAll("[data-move-down]")) {
  button.addEventListener("click", () => moveRow(button, 1));
}

for (const button of document.querySelectorAll("[data-remove-profile]")) {
  button.addEventListener("click", () => {
    const row = button.closest("tr");
    const name = row?.dataset.profileName || "this profile";
    if (document.querySelectorAll("[data-profile-row]").length <= 1) {
      window.alert("At least one selection profile is required.");
      return;
    }
    if (!window.confirm(`Remove ${name}?`)) {
      return;
    }
    row?.remove();
    form.requestSubmit();
  });
}

for (const button of document.querySelectorAll("[data-remove-preset]")) {
  button.addEventListener("click", () => {
    const row = button.closest("[data-preset-row]");
    const name = row?.dataset.presetName || "this preset";
    if (document.querySelectorAll("[data-preset-row]").length <= 1) {
      window.alert("At least one filter preset is required.");
      return;
    }
    if (!window.confirm(`Remove ${name}?`)) {
      return;
    }
    row?.remove();
    form.requestSubmit();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  for (const range of document.querySelectorAll("[data-preset-range]")) {
    const row = range.closest("[data-preset-row]");
    const minimum = range.querySelector("[data-range-min]");
    const maximum = range.querySelector("[data-range-max]");
    const field = (handle) => row.querySelector(`[aria-label="Preset ${handle.dataset.rangeKey}"]`);
    for (const handle of [minimum, maximum]) {
      handle.addEventListener("input", () => {
        field(handle).value = handle.value;
        const other = handle === minimum ? maximum : minimum;
        if (field(other).value !== "") {
          field(other).value = other.value;
        }
      });
      field(handle).addEventListener("input", () => {
        const value = field(handle).value;
        handle.value = value || (handle === minimum ? "0" : "1");
        handle.dispatchEvent(new Event("input"));
        field(handle).value = value;
      });
    }
    range.querySelector("[data-clear-range]").addEventListener("click", () => {
      minimum.value = "0";
      maximum.value = "1";
      minimum.dispatchEvent(new Event("input"));
      maximum.dispatchEvent(new Event("input"));
      field(minimum).value = "";
      field(maximum).value = "";
    });
  }
  for (const row of document.querySelectorAll("[data-preset-row]")) {
    for (const checkbox of row.querySelectorAll("[data-preset-list]")) {
      const key = checkbox.dataset.presetList;
      const field = row.querySelector(`[aria-label="Preset ${key}"]`);
      checkbox.addEventListener("change", () => {
        let values = field.value.split(",").map((value) => value.trim()).filter(Boolean);
        values = values.filter((value) => value !== checkbox.value);
        if (checkbox.checked) values.push(checkbox.value);
        field.value = values.join(",");
      });
      field.addEventListener("input", () => {
        checkbox.checked = field.value.split(",").map((value) => value.trim()).includes(checkbox.value);
      });
    }
    for (const select of row.querySelectorAll("[data-preset-select]")) {
      const key = select.dataset.presetSelect;
      const field = row.querySelector(`[aria-label="Preset ${key}"]`);
      select.addEventListener("change", () => {
        field.value = select.value === "all" ? "" : select.value;
      });
      field.addEventListener("input", () => {
        const values = field.value.split(",").map((value) => value.trim()).filter(Boolean);
        if (!values.length) {
          select.value = "all";
        } else if (values.length === 1) {
          select.value = values[0];
        } else if (values.includes("not_rejected")) {
          select.value = "not_rejected";
        } else if (values.includes("accepted") && values.includes("none")) {
          select.value = "not_rejected";
        } else {
          select.value = values[0];
        }
      });
    }
    for (const date of row.querySelectorAll("[data-preset-date]")) {
      const field = row.querySelector(`[aria-label="Preset ${date.dataset.presetDate}"]`);
      date.addEventListener("input", () => { field.value = date.value; });
      field.addEventListener("input", () => { date.value = field.value; });
    }
  }
});
