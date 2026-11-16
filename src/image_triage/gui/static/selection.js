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

  function currentFilters() {
    var params = new URLSearchParams(window.location.search);
    ["page", "view", "tab", "sort", "order"].forEach(function (key) {
      params.delete(key);
    });
    var filters = {};
    params.forEach(function (value, key) {
      if (key === "q") {
        key = "search";
      }
      if (Object.prototype.hasOwnProperty.call(filters, key)) {
        if (Array.isArray(filters[key])) {
          filters[key].push(value);
        } else {
          filters[key] = [filters[key], value];
        }
      } else {
        filters[key] = value;
      }
    });
    return filters;
  }

  function postJson(url, body) {
    return window
      .fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("request failed: " + response.status);
        }
        return response.json();
      });
  }

  function keepLabel(keep) {
    if (keep === true) {
      return "accepted";
    }
    if (keep === false) {
      return "rejected";
    }
    return "undecided";
  }

  function updateBadges(photoId, keep) {
    document.querySelectorAll('[data-photo-id="' + photoId + '"]').forEach(function (card) {
      var existing = card.querySelector(".status-badge");
      if (existing) {
        existing.remove();
      }
      if (keep === true || keep === false) {
        var badge = document.createElement("span");
        badge.className = "status-badge " + (keep ? "status-accepted" : "status-rejected");
        badge.textContent = keepLabel(keep);
        card.appendChild(badge);
      }
    });
    document.querySelectorAll('[data-review-photo-id="' + photoId + '"]').forEach(function (card) {
      var badge = card.querySelector(".status-badge");
      if (badge) {
        badge.className = "status-badge " + (keep ? "status-accepted" : "status-rejected");
        badge.textContent = keepLabel(keep);
      } else if (keep === true || keep === false) {
        var created = document.createElement("span");
        created.className = "status-badge " + (keep ? "status-accepted" : "status-rejected");
        created.textContent = keepLabel(keep);
        card.appendChild(created);
      }
    });
  }

  function changeStatus(locationIds, status, after) {
    postJson("/api/status", { location_ids: locationIds, status: status }).then(function (data) {
      if (after) {
        after(data);
      }
    });
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

  var reviewPhotos = [];

  function photoFolder(photo) {
    return photo.path.indexOf("/") === -1 ? "." : photo.path.slice(0, photo.path.lastIndexOf("/"));
  }

  function reviewScopeValue(root, folder) {
    return root + "\n" + folder;
  }

  function populateReviewScope() {
    var rootSelect = document.querySelector("[data-review-root]");
    var folderSelect = document.querySelector("[data-review-folder]");
    if (!rootSelect || !folderSelect) {
      return;
    }
    var previousRoot = rootSelect.value;
    var previousFolder = folderSelect.value;
    rootSelect.innerHTML = '<option value="">All roots</option>';
    folderSelect.innerHTML = '<option value="">All folders</option>';
    var roots = [];
    var folders = [];
    reviewPhotos.forEach(function (photo) {
      if (roots.indexOf(photo.root) === -1) {
        roots.push(photo.root);
      }
      var key = reviewScopeValue(photo.root, photoFolder(photo));
      if (!folders.some(function (item) { return item.key === key; })) {
        folders.push({ key: key, root: photo.root, folder: photoFolder(photo) });
      }
    });
    roots.sort().forEach(function (root) {
      var option = document.createElement("option");
      option.value = root;
      option.textContent = root;
      rootSelect.appendChild(option);
    });
    folders
      .sort(function (a, b) { return a.key.localeCompare(b.key); })
      .forEach(function (item) {
        var option = document.createElement("option");
        option.value = item.key;
        option.textContent = item.folder === "." ? item.root : item.folder;
        option.title = item.root;
        folderSelect.appendChild(option);
      });
    if (Array.from(rootSelect.options).some(function (option) { return option.value === previousRoot; })) {
      rootSelect.value = previousRoot;
    }
    if (
      Array.from(folderSelect.options).some(function (option) { return option.value === previousFolder; })
    ) {
      folderSelect.value = previousFolder;
    }
  }

  function reviewCard(photo) {
    var card = document.createElement("article");
    card.className = "review-card";
    card.setAttribute("data-review-photo-id", String(photo.photo_id));
    card.setAttribute("data-review-location-id", String(photo.location_id));
    card.setAttribute("data-root", photo.root);
    card.setAttribute("data-folder", photoFolder(photo));

    var link = document.createElement("a");
    link.href = photo.url;
    var image = document.createElement("img");
    image.src = photo.media;
    image.alt = photo.path;
    image.loading = "lazy";
    link.appendChild(image);
    card.appendChild(link);

    var meta = document.createElement("div");
    meta.className = "meta";
    var name = document.createElement("div");
    name.className = "name";
    name.textContent = photo.name;
    var path = document.createElement("div");
    path.className = "path";
    path.textContent = photo.root + "/" + photo.path;
    path.title = path.textContent;
    meta.appendChild(name);
    meta.appendChild(path);
    var score = document.createElement("div");
    score.textContent = "score " + Number(photo.score).toFixed(2) + " - rating " + photo.rating + "/5";
    meta.appendChild(score);
    card.appendChild(meta);

    if (photo.keep === true || photo.keep === false) {
      var badge = document.createElement("span");
      badge.className = "status-badge " + (photo.keep ? "status-accepted" : "status-rejected");
      badge.textContent = keepLabel(photo.keep);
      card.appendChild(badge);
    }

    var actions = document.createElement("div");
    actions.className = "review-actions";

    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button-secondary";
    remove.textContent = "Remove";
    remove.addEventListener("click", function () {
      subtractSelected([photo.location_id]);
      reviewPhotos = reviewPhotos.filter(function (item) {
        return item.location_id !== photo.location_id;
      });
      renderReview();
    });
    actions.appendChild(remove);

    ["accepted", "rejected"].forEach(function (status) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = status === "accepted" ? "" : "button-secondary";
      button.textContent = status === "accepted" ? "Accept" : "Reject";
      button.addEventListener("click", function () {
        changeStatus([photo.location_id], status, function () {
          photo.keep = status === "accepted";
          updateBadges(photo.photo_id, photo.keep);
        });
      });
      actions.appendChild(button);
    });

    card.appendChild(actions);
    return card;
  }

  function renderReview() {
    var grid = document.querySelector("[data-review-grid]");
    if (!grid) {
      return;
    }
    var root = document.querySelector("[data-review-root]").value;
    var folder = document.querySelector("[data-review-folder]").value;
    var visible = reviewPhotos.filter(function (photo) {
      if (root && photo.root !== root) {
        return false;
      }
      if (folder && reviewScopeValue(photo.root, photoFolder(photo)) !== folder) {
        return false;
      }
      return true;
    });
    grid.innerHTML = "";
    visible.forEach(function (photo) {
      grid.appendChild(reviewCard(photo));
    });
    var count = document.querySelector("[data-review-count]");
    if (count) {
      count.textContent = String(visible.length) + (visible.length === reviewPhotos.length ? "" : " / " + reviewPhotos.length);
    }
    var empty = document.querySelector("[data-review-empty]");
    if (empty) {
      empty.hidden = visible.length > 0;
    }
  }

  function openReview() {
    var selected = readSelected();
    if (selected.length === 0) {
      window.alert("Select at least one photo first.");
      return;
    }
    postJson("/api/photos", { location_ids: selected }).then(function (data) {
      reviewPhotos = data.photos || [];
      var found = new Set(
        reviewPhotos.map(function (photo) {
          return photo.location_id;
        })
      );
      var pruned = selected.filter(function (id) {
        return found.has(id);
      });
      if (pruned.length !== selected.length) {
        writeSelected(pruned);
        applySelection(pruned);
      }
      var missing = document.querySelector("[data-review-missing]");
      if (missing) {
        missing.textContent = data.missing && data.missing.length
          ? data.missing.length + " stale id(s) removed"
          : "";
      }
      populateReviewScope();
      renderReview();
      var dialog = document.getElementById("review-dialog");
      if (dialog) {
        dialog.showModal();
      }
    });
  }

  function changeFilteredStatus(status) {
    var filters = currentFilters();
    var query = new URLSearchParams();
    Object.keys(filters).forEach(function (key) {
      var value = filters[key];
      if (Array.isArray(value)) {
        value.forEach(function (item) { query.append(key, item); });
      } else {
        query.append(key, value);
      }
    });
    var url = "/api/photo-ids" + (query.toString() ? "?" + query.toString() : "");
    window
      .fetch(url)
      .then(function (response) { return response.json(); })
      .then(function (data) {
        var total = data.total || 0;
        if (total === 0) {
          window.alert("No photos match the current filters.");
          return;
        }
        if (!window.confirm((status === "accepted" ? "Accept " : "Reject ") + total + " filtered photos?")) {
          return;
        }
        postJson("/api/status", { filters: filters, status: status }).then(function () {
          window.location.reload();
        });
      });
  }

  function applyLocationIds(ids) {
    writeSelected(ids || []);
    applySelection(ids || []);
  }

  function waitForJob(jobId) {
    return new Promise(function (resolve, reject) {
      function poll() {
        window
          .fetch("/jobs/" + jobId)
          .then(function (response) { return response.json(); })
          .then(function (job) {
            if (job.status === "completed") {
              resolve(job.result || {});
            } else if (job.status === "failed") {
              reject(new Error((job.result && job.result.error) || "job failed"));
            } else {
              window.setTimeout(poll, 750);
            }
          })
          .catch(reject);
      }
      poll();
    });
  }

  function runBest() {
    var status = document.querySelector("[data-best-status]");
    var profileSelect = document.querySelector("[data-profile-select]");
    var nField = document.querySelector("[data-best-n]");
    var modeField = document.querySelector("[data-best-mode]");
    var selectedMode = modeField ? modeField.value : "add";
    var groupBest = selectedMode === "group";
    var mode = groupBest ? "replace" : selectedMode;
    var body = {
      filters: currentFilters(),
      mode: mode,
      existing_ids: mode === "add" ? readSelected() : [],
      profile: profileSelect ? profileSelect.value : undefined,
    };
    if (!groupBest) {
      body.n = nField ? Math.max(0, Number(nField.value) || 0) : 20;
    }
    if (status) {
      status.textContent = "selecting...";
    }
    postJson(groupBest ? "/api/select-group-best" : "/api/select-best", body)
      .then(function (data) {
        if (data.async && data.job_id) {
          if (status) {
            status.textContent = "running in background...";
          }
          return waitForJob(data.job_id);
        }
        return data;
      })
      .then(function (result) {
        applyLocationIds(result.location_ids || []);
        if (status) {
          var summary = result.summary || {};
          status.textContent =
            (summary.selected || 0) +
            " selected" +
            (summary.total ? " / " + summary.total + " total" : "") +
            (summary.candidates ? " from " + summary.candidates + " candidates" : "");
        }
      })
      .catch(function (error) {
        if (status) {
          status.textContent = "error: " + error.message;
        }
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
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

    function changeSelectedStatus(status) {
      var selected = readSelected();
      if (selected.length === 0) {
        window.alert("Select at least one photo first.");
        return;
      }
      if (
        !window.confirm(
          (status === "accepted" ? "Accept " : "Reject ") + selected.length + " selected photos?"
        )
      ) {
        return;
      }
      changeStatus(selected, status, function () {
        window.location.reload();
      });
    }

    var acceptSelected = document.querySelector("[data-accept-selected]");
    if (acceptSelected) {
      acceptSelected.addEventListener("click", function () {
        changeSelectedStatus("accepted");
      });
    }

    var rejectSelected = document.querySelector("[data-reject-selected]");
    if (rejectSelected) {
      rejectSelected.addEventListener("click", function () {
        changeSelectedStatus("rejected");
      });
    }

    var reviewOpen = document.querySelector("[data-open-review]");
    if (reviewOpen) {
      reviewOpen.addEventListener("click", openReview);
    }

    var reviewClose = document.querySelector("[data-review-close]");
    if (reviewClose) {
      reviewClose.addEventListener("click", function () {
        var dialog = document.getElementById("review-dialog");
        if (dialog) {
          dialog.close();
        }
      });
    }

    ["[data-review-root]", "[data-review-folder]"].forEach(function (selector) {
      var field = document.querySelector(selector);
      if (field) {
        field.addEventListener("change", renderReview);
      }
    });

    var acceptFiltered = document.querySelector("[data-accept-filtered]");
    if (acceptFiltered) {
      acceptFiltered.addEventListener("click", function () {
        changeFilteredStatus("accepted");
      });
    }

    var rejectFiltered = document.querySelector("[data-reject-filtered]");
    if (rejectFiltered) {
      rejectFiltered.addEventListener("click", function () {
        changeFilteredStatus("rejected");
      });
    }

    var profileSelect = document.querySelector("[data-profile-select]");
    if (profileSelect) {
      profileSelect.addEventListener("change", function () {
        var option = profileSelect.options[profileSelect.selectedIndex];
        var nField = document.querySelector("[data-best-n]");
        if (option && nField && option.dataset.profileN) {
          nField.value = option.dataset.profileN;
        }
      });
    }

    var bestRun = document.querySelector("[data-best-run]");
    if (bestRun) {
      bestRun.addEventListener("click", runBest);
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

    var reviewExport = document.querySelector("[data-review-export]");
    if (reviewExport && exportDialog) {
      reviewExport.addEventListener("click", function () {
        var reviewDialog = document.getElementById("review-dialog");
        if (reviewDialog) {
          reviewDialog.close();
        }
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