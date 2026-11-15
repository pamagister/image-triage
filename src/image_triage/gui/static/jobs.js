/* Header job-status indicator. Jobs themselves remain read-only. */
(function () {
  "use strict";

  var label = document.querySelector("[data-header-job-count]");
  var link = document.querySelector("[data-header-jobs]");
  if (!label || !link) {
    return;
  }

  function refresh() {
    window
      .fetch("/api/jobs/active")
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        var count = Number(data.count || 0);
        label.textContent = count > 0 ? String(count) : "";
        label.hidden = count === 0;
        link.classList.toggle("has-jobs", count > 0);
      })
      .catch(function () {
        /* header status is best-effort */
      });
  }

  refresh();
  window.setInterval(refresh, 5000);
})();