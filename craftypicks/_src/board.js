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

  /* There used to be a rule here that a click outside an open panel closed
     it. It was written when the only way out of a tall panel was scrolling
     back to its summary, and it had a consequence nobody asked for: opening
     a second card counted as a click outside the first, so exactly one card
     could be open at a time.

     That is the wrong behaviour for a board. Comparing two games -- or two
     starters, or the same hitter against two arms -- is the whole reason
     the detail exists, and the page made it impossible. Every panel now
     carries a close button at its foot and Escape still works, so the rule
     was redundant as well as harmful. Removed.

     <details> elements are independent by default. Letting them be is not
     a feature; it is what the element already does. */

  /* Escape closes the most recently opened panel, as every other disclosure
     on the web does, and returns focus to the summary that opened it. With
     several open it takes them one at a time rather than clearing the
     board, so a mis-keyed Escape costs one card and not the comparison you
     just built. */
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

  /* The game picker on the NFL prop boards. Progressive: the chips are
     ordinary anchors pointing at each section, so with no JavaScript they
     scroll to the right group and nothing is lost. With JavaScript they
     filter instead, which on a sixteen-game slate is the difference
     between finding a player and scrolling for him.

     Filtering hides sections with the `hidden` attribute rather than a
     class, so anything that reads the DOM -- a find-in-page, a screen
     reader -- agrees with what the eye sees. */
  var picker = document.querySelector(".gsel");
  if (picker) {
    picker.addEventListener("click", function (e) {
      var chip = e.target.closest ? e.target.closest(".gchip") : null;
      if (!chip) { return; }
      e.preventDefault();
      var want = chip.getAttribute("data-game") || "";
      Array.prototype.forEach.call(
        picker.querySelectorAll(".gchip"), function (c) {
          c.classList.toggle("on", c === chip);
        });
      Array.prototype.forEach.call(
        document.querySelectorAll(".gsec"), function (s) {
          s.hidden = !!want && s.getAttribute("data-game") !== want;
        });
      /* Back to the top of the board, not of the page: the reader just
         chose a game and wants to see it, and leaving them mid-scroll in
         a list that just got shorter is disorienting. */
      picker.scrollIntoView({block: "start"});
    });
  }
})();
