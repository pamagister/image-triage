(function () {
  "use strict";

  document.addEventListener("keydown", function (event) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.repeat) return;
    var target = event.target;
    if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
    if (document.querySelector("dialog[open]")) return;
    var element = null;
    if (event.key === "ArrowLeft") element = document.querySelector("[data-detail-previous]");
    else if (event.key === "ArrowRight") element = document.querySelector("[data-detail-next]");
    else if (event.key.toLowerCase() === "a") element = document.querySelector('[data-decision="accepted"]');
    else if (event.key.toLowerCase() === "r") element = document.querySelector('[data-decision="rejected"]');
    else if (/^[1-5]$/.test(event.key)) element = document.querySelector('[data-rate="' + event.key + '"]');
    if (element) {
      event.preventDefault();
      element.click();
    }
  });
})();
