/* Progressive by design: the page is correct without any of this.
   <details> already opens and closes on its own summary. All this adds is
   ways to close one that do not require scrolling back to where you began,
   because the panel is taller than a phone and the summary is off-screen by
   the time anyone wants it again. */
(function () {
  "use strict";

  function openPanels() {
    return Array.prototype.slice.call(
      document.querySelectorAll("details[open]"));
  }

  function shut(d) {
    d.open = false;
    var s = d.querySelector("summary");
    if (s) { s.scrollIntoView({block: "nearest"}); }
  }

  /* A click outside an open panel closes it. Clicks inside must not, or
     selecting text in the panel would shut it mid-drag. */
  document.addEventListener("click", function (e) {
    openPanels().forEach(function (d) {
      if (!d.contains(e.target)) { d.open = false; }
    });
  });

  /* Escape closes the innermost open panel, as every other disclosure on
     the web does, and returns focus to the summary that opened it. */
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") { return; }
    var open = openPanels();
    if (!open.length) { return; }
    var last = open[open.length - 1];
    last.open = false;
    var s = last.querySelector("summary");
    if (s) { s.focus(); }
  });

  /* A close control at the FOOT of each panel, added the first time it
     opens. Registered in the capture phase because `toggle` does not
     bubble -- without `true` this listener fires for nothing and the bug
     looks like the button was never written. */
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!d || d.tagName !== "DETAILS" || !d.open) { return; }
    if (d.getAttribute("data-closed") === "1") { return; }
    d.setAttribute("data-closed", "1");
    var b = document.createElement("button");
    b.type = "button";
    b.className = "d-close";
    b.textContent = d.getAttribute("data-close") || "Close";
    b.addEventListener("click", function (ev) {
      ev.stopPropagation();
      shut(d);
      var s = d.querySelector("summary");
      if (s) { s.focus(); }
    });
    d.appendChild(b);
  }, true);
})();
