/*
 * Shared UI helpers: delayed action tooltips and generic dialog close buttons.
 *
 * The tooltip is a single fixed-position element. It is appended to the active
 * dialog when the trigger lives inside one, because modal dialogs occupy the
 * browser top layer and would otherwise cover a tooltip attached to the body.
 */
(function () {
  "use strict";

  var TOOLTIP_DELAY = 2200;
  var tooltip = null;
  var active = null;
  var timer = null;

  function ensureTooltip(parent) {
    if (!tooltip) {
      tooltip = document.createElement("div");
      tooltip.id = "ui-tooltip";
      tooltip.className = "ui-tooltip";
      tooltip.setAttribute("role", "tooltip");
      tooltip.hidden = true;
    }
    if (tooltip.parentElement !== parent) {
      parent.appendChild(tooltip);
    }
    return tooltip;
  }

  function position(trigger) {
    var tip = ensureTooltip(trigger.closest("dialog") || document.body);
    var rect = trigger.getBoundingClientRect();
    var margin = 8;
    var gap = 6;
    var bounds = tip.getBoundingClientRect();
    var left = rect.left;
    var top = rect.bottom + gap;
    if (left + bounds.width > window.innerWidth - margin) {
      left = window.innerWidth - margin - bounds.width;
    }
    if (left < margin) {
      left = margin;
    }
    if (top + bounds.height > window.innerHeight - margin) {
      top = rect.top - bounds.height - gap;
    }
    if (top < margin) {
      top = margin;
    }
    tip.style.left = Math.round(left) + "px";
    tip.style.top = Math.round(top) + "px";
  }

  function hide() {
    if (timer) {
      window.clearTimeout(timer);
      timer = null;
    }
    if (active) {
      active.removeAttribute("aria-describedby");
      active = null;
    }
    if (tooltip) {
      tooltip.hidden = true;
    }
  }

  function show(trigger) {
    hide();
    var text = trigger.getAttribute("data-tooltip");
    if (!text) {
      return;
    }
    active = trigger;
    var tip = ensureTooltip(trigger.closest("dialog") || document.body);
    tip.textContent = text;
    tip.hidden = false;
    trigger.setAttribute("aria-describedby", tip.id);
    position(trigger);
  }

  function schedule(trigger) {
    hide();
    timer = window.setTimeout(function () {
      timer = null;
      show(trigger);
    }, TOOLTIP_DELAY);
  }

  document.addEventListener("pointerover", function (event) {
    var trigger = event.target.closest("[data-tooltip]");
    if (!trigger || trigger.contains(event.relatedTarget)) {
      return;
    }
    schedule(trigger);
  });

  document.addEventListener("pointerout", function (event) {
    var trigger = event.target.closest("[data-tooltip]");
    if (!trigger || trigger.contains(event.relatedTarget)) {
      return;
    }
    hide();
  });

  document.addEventListener("focusin", function (event) {
    var trigger = event.target.closest("[data-tooltip]");
    if (trigger) {
      schedule(trigger);
    }
  });

  document.addEventListener("focusout", function (event) {
    var trigger = event.target.closest("[data-tooltip]");
    if (trigger) {
      hide();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      hide();
    }
  });

  window.addEventListener(
    "scroll",
    function () {
      if (tooltip && !tooltip.hidden) {
        hide();
      }
    },
    true
  );

  document.addEventListener("click", function (event) {
    hide();
    var close = event.target.closest("[data-dialog-close]");
    if (!close) {
      return;
    }
    var dialog = close.closest("dialog");
    if (dialog) {
      event.preventDefault();
      dialog.close();
    }
  });
})();