(function () {
  "use strict";

  var section = document.querySelector("[data-similarity]");
  if (!section) return;
  var slider = section.querySelector("[data-similarity-distance]");
  var output = section.querySelector("[data-similarity-value]");
  var status = section.querySelector("[data-similarity-status]");
  var results = section.querySelector("[data-similarity-results]");
  var more = section.querySelector("[data-similarity-more]");
  var cursor = null;
  var controller = null;
  var debounce = null;

  function render(item) {
    var card = document.createElement("li");
    card.className = "similarity-card";
    var link = document.createElement("a");
    var url = new URL(window.location.href);
    url.pathname = "/photo/" + item.photo_id;
    url.searchParams.set("location_id", item.location_id);
    link.href = url.toString();
    var image = document.createElement("img");
    image.src = "/media/location/" + item.location_id;
    image.alt = item.name;
    image.loading = "lazy";
    var name = document.createElement("span");
    name.textContent = item.name;
    var reason = document.createElement("small");
    reason.textContent = item.identical ? "identical file" : "hash difference " + item.distance + "/64";
    if (item.same_group) reason.textContent += " · stored group";
    link.title = item.root + "/" + item.path;
    link.append(image, name, reason);
    card.appendChild(link);
    results.appendChild(card);
  }

  async function load(append) {
    if (controller) controller.abort();
    controller = new AbortController();
    var params = new URLSearchParams({
      location_id: section.dataset.locationId,
      distance: slider.value,
    });
    if (append && cursor) params.set("after", cursor);
    if (!append) results.replaceChildren();
    more.hidden = true;
    status.textContent = "Loading suggestions…";
    try {
      var response = await fetch("/api/photo/" + section.dataset.photoId + "/similar?" + params, { signal: controller.signal });
      if (!response.ok) throw new Error("Could not load suggestions (" + response.status + ")");
      var data = await response.json();
      data.items.forEach(render);
      cursor = data.next_cursor;
      more.hidden = !cursor;
      status.textContent = !data.hash_available
        ? "No perceptual hash is available; only identical files can be shown."
        : results.children.length ? "Suggestions ordered by visual hash difference." : "No matching photos at this setting.";
    } catch (error) {
      if (error.name !== "AbortError") status.textContent = error.message;
    }
  }

  slider.addEventListener("input", function () {
    output.textContent = slider.value;
    var url = new URL(window.location.href);
    url.searchParams.set("distance", slider.value);
    window.history.replaceState(null, "", url);
    clearTimeout(debounce);
    debounce = setTimeout(function () { load(false); }, 150);
  });
  more.addEventListener("click", function () { load(true); });
  load(false);
})();
