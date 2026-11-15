/*
 * Ephemeral, browser-local selection for the library page.
 *
 * Selection lives in localStorage so it survives filtering and pagination within the
 * session. It is intentionally not stored on the server: exporting always sends the
 * exact ids to use.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "image-triage:selected";
  var TREE_KEY = "image-triage:open-folders";

  function readSelected() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      var parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.map(Number).filter(Number.isFinite) : [];
    } catch (err) {
      return [];
    }
  }

  function writeSelected(ids) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
    } catch (err) {
      /* storage may be unavailable; selection still works for this page */
    }
  }

  function currentQuery() {
    var params = new URLSearchParams(window.location.search);
    params.delete("page");
    return params.toString();
  }

  function readOpenFolders() {
    try {
      var raw = window.localStorage.getItem(TREE_KEY);
      var parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (err) {
      return {};
    }
  }

  function writeOpenFolders(state) {
    try {
      window.localStorage.setItem(TREE_KEY, JSON.stringify(state));
    } catch (err) {
      /* storage may be unavailable; expansion still works for this page */
    }
  }

  function folderKey(details) {
    var node = details.closest("[data-folder-node]");
    if (!node) {
      return null;
    }
    return node.getAttribute("data-root") + "\n" + node.getAttribute("data-folder");
  }

  function restoreOpenFolders() {
    var open = readOpenFolders();
    document.querySelectorAll("[data-folder-tree] details").forEach(function (details) {
      var key = folderKey(details);
      if (key && Object.prototype.hasOwnProperty.call(open, key)) {
        details.open = Boolean(open[key]);
      }
    });
  }

  function folderFilterUrl() {
    var params = new URLSearchParams(window.location.search);
    params.delete("page");
    params.delete("folder");
    var checked = Array.from(document.querySelectorAll("[data-folder-filter]")).filter(
      function (box) {
        return box.checked;
      }
    );
    if (checked.length > 0) {
      params.delete("root");
      var roots = [];
      checked.forEach(function (box) {
        params.append("folder", box.getAttribute("data-folder"));
        var root = box.getAttribute("data-root");
        if (roots.indexOf(root) === -1) {
          roots.push(root);
        }
      });
      roots.forEach(function (root) {
        params.append("root", root);
      });
    }
    return "/?" + params.toString();
  }

  function applySelection(selected) {
    var chosen = new Set(selected);
    document.querySelectorAll("[data-select-photo]").forEach(function (box) {
      box.checked = chosen.has(Number(box.value));
    });
    var counter = document.querySelector("[data-selected-count]");
    if (counter) {
      counter.textContent = String(chosen.size);
    }
  }

  function unionSelected(ids) {
    var selected = readSelected();
    var seen = new Set(selected);
    ids.forEach(function (id) {
      var value = Number(id);
      if (Number.isFinite(value) && !seen.has(value)) {
        seen.add(value);
        selected.push(value);
      }
    });
    writeSelected(selected);
    applySelection(selected);
  }

  function subtractSelected(ids) {
    var remove = new Set(ids.map(Number).filter(Number.isFinite));
    var selected = readSelected().filter(function (id) {
      return !remove.has(id);
    });
    writeSelected(selected);
    applySelection(selected);
  }

  function toggle(id, on) {
    var selected = readSelected();
    var index = selected.indexOf(id);
    if (on && index === -1) {
      selected.push(id);
    } else if (!on && index !== -1) {
      selected.splice(index, 1);
    }
    writeSelected(selected);
    applySelection(selected);
  }

  function setPhotoIdsField(ids) {
    var field = document.querySelector("[data-photo-ids]");
    if (field) {
      field.value = ids.join(",");
    }
  }

  function setScope(scope) {
    var field = document.querySelector("[data-scope]");
    if (field) {
      field.value = scope;
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.querySelector("[data-export-form]");
    if (!form) {
      return;
    }

    applySelection(readSelected());
    restoreOpenFolders();

    document.querySelectorAll("[data-dual-range]").forEach(function (group) {
      var minInput = group.querySelector("[data-range-min]");
      var maxInput = group.querySelector("[data-range-max]");
      var fill = group.querySelector("[data-range-fill]");
      if (!minInput || !maxInput || !fill) {
        return;
      }
      var minOutput = group.querySelector('[data-output-for="' + minInput.name + '"]');
      var maxOutput = group.querySelector('[data-output-for="' + maxInput.name + '"]');

      function update(changed) {
        var low = Number(minInput.value);
        var high = Number(maxInput.value);
        if (low > high) {
          if (changed === minInput) {
            high = low;
            maxInput.value = String(high);
          } else {
            low = high;
            minInput.value = String(low);
          }
        }
        if (minOutput) {
          minOutput.textContent = low.toFixed(2);
        }
        if (maxOutput) {
          maxOutput.textContent = high.toFixed(2);
        }
        fill.style.left = low * 100 + "%";
        fill.style.width = (high - low) * 100 + "%";
      }

      minInput.addEventListener("input", function () {
        update(minInput);
      });
      maxInput.addEventListener("input", function () {
        update(maxInput);
      });
      update(minInput);
    });

    document.addEventListener(
      "toggle",
      function (event) {
        var details = event.target.closest("details");
        if (!details) {
          return;
        }
        var key = folderKey(details);
        if (!key) {
          return;
        }
        var open = readOpenFolders();
        open[key] = details.open;
        writeOpenFolders(open);
      },
      true
    );

    document.addEventListener("click", function (event) {
      var summary = event.target.closest(".folder-tree summary");
      if (!summary) {
        return;
      }
      var box = event.target.closest("[data-folder-filter]");
      if (box) {
        // The checkbox lives inside a <summary>; stop the click from toggling the folder.
        event.preventDefault();
        event.stopPropagation();
        box.checked = !box.checked;
        box.dispatchEvent(new Event("change", { bubbles: true }));
        return;
      }
      var link = event.target.closest("a");
      if (link && summary.contains(link)) {
        // Let the link navigate without also collapsing the folder.
        event.preventDefault();
        window.location.href = link.href;
      }
    });

    document.addEventListener("change", function (event) {
      var box = event.target.closest("[data-select-photo]");
      if (box) {
        toggle(Number(box.value), box.checked);
        return;
      }
      if (event.target.closest("[data-folder-filter]")) {
        window.location.href = folderFilterUrl();
      }
    });

    function fetchFilteredIds(then) {
      var query = currentQuery();
      var url = "/api/photo-ids" + (query ? "?" + query : "");
      window
        .fetch(url)
        .then(function (response) {
          return response.json();
        })
        .then(function (data) {
          then(data.ids || []);
        });
    }

    var selectAll = document.querySelector("[data-select-all]");
    if (selectAll) {
      selectAll.addEventListener("click", function () {
        fetchFilteredIds(unionSelected);
      });
    }

    var deselectAll = document.querySelector("[data-deselect-all]");
    if (deselectAll) {
      deselectAll.addEventListener("click", function () {
        fetchFilteredIds(subtractSelected);
      });
    }

    var clear = document.querySelector("[data-clear]");
    if (clear) {
      clear.addEventListener("click", function () {
        if (!window.confirm("Clear all selected photos?")) {
          return;
        }
        writeSelected([]);
        applySelection([]);
      });
    }

    var exportOpen = document.querySelector("[data-export-open]");
    var exportDialog = document.getElementById("export-dialog");
    if (exportOpen && exportDialog) {
      exportOpen.addEventListener("click", function () {
        setScope("selected");
        setPhotoIdsField(readSelected());
        exportDialog.showModal();
      });
    }

    document.querySelectorAll("[data-export-close]").forEach(function (button) {
      button.addEventListener("click", function () {
        var dialog = button.closest("dialog");
        if (dialog) {
          dialog.close();
        }
      });
    });

    var scope = document.querySelector("[data-scope]");
    if (scope) {
      scope.addEventListener("change", function () {
        if (scope.value !== "selected") {
          setPhotoIdsField([]);
        }
      });
    }
  });
})();