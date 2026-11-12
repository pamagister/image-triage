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

    document.addEventListener("change", function (event) {
      var box = event.target.closest("[data-select-photo]");
      if (box) {
        toggle(Number(box.value), box.checked);
      }
    });

    var selectAll = document.querySelector("[data-select-all]");
    if (selectAll) {
      selectAll.addEventListener("click", function () {
        var query = currentQuery();
        var url = "/api/photo-ids" + (query ? "?" + query : "");
        window
          .fetch(url)
          .then(function (response) {
            return response.json();
          })
          .then(function (data) {
            writeSelected(data.ids || []);
            applySelection(data.ids || []);
          });
      });
    }

    var clear = document.querySelector("[data-clear]");
    if (clear) {
      clear.addEventListener("click", function () {
        writeSelected([]);
        applySelection([]);
      });
    }

    var exportAll = document.querySelector("[data-export-all]");
    if (exportAll) {
      exportAll.addEventListener("click", function () {
        setScope("filtered");
        setPhotoIdsField([]);
        form.submit();
      });
    }

    var exportSelected = document.querySelector("[data-export-selected]");
    if (exportSelected) {
      exportSelected.addEventListener("click", function (event) {
        var selected = readSelected();
        if (selected.length === 0) {
          event.preventDefault();
          window.alert("Select at least one photo first.");
          return;
        }
        setScope("selected");
        setPhotoIdsField(selected);
        form.submit();
      });
    }
  });
})();