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
      var mode = chip.getAttribute("data-filter") || "";
      Array.prototype.forEach.call(
        picker.querySelectorAll(".gchip"), function (c) {
          c.classList.toggle("on", c === chip);
        });
      /* Two shapes of board share this picker. The card boards group into
         one <section> per fixture; the list board is one flat list whose
         rows each carry their own fixture. Filtering both by the same
         attribute keeps one picker and one code path. */
      Array.prototype.forEach.call(
        document.querySelectorAll(".gsec,.pl"), function (s) {
          if (mode === "edges") {
            s.hidden = s.getAttribute("data-edge") !== "1";
          } else if (want) {
            s.hidden = s.getAttribute("data-game") !== want;
          } else {
            s.hidden = false;
          }
        });
      /* Back to the top of the board, not of the page: the reader just
         chose a game and wants to see it, and leaving them mid-scroll in
         a list that just got shorter is disorienting. */
      picker.scrollIntoView({block: "start"});
    });
  }
  /* The sport row scrolls, and on a narrow phone the sport the reader is
     actually looking at can start off-screen. Nudge it into view. Not a
     smooth scroll: this happens on load, and animating the nav on arrival
     looks like a fault. */
  var sports = document.querySelector(".nav-links");
  if (sports) {
    var here = sports.querySelector("a.on");
    if (here) {
      /* Measured against the row's own box, not offsetLeft: the pills have
         no positioned ancestor, so offsetLeft is relative to the page and
         scrolled the first pill half out of view -- which looked like a
         clipped word rather than a nudge. */
      var a = here.getBoundingClientRect();
      var b = sports.getBoundingClientRect();
      if (a.right > b.right) { sports.scrollLeft += (a.right - b.right) + 12; }
      else if (a.left < b.left) { sports.scrollLeft -= (b.left - a.left) + 12; }
    }
  }
})();

/* Live scores for started college games (NCAAB, NCAAF).

   Each college card carries data-sport, data-espn, data-home, data-away,
   data-tip and, when we made a pick, data-side and data-line. Once a game
   has tipped off and the build did not already print its final, this asks
   ESPN's free scoreboard for that day and fills the card's empty strip:
   the score, and whether our side is covering (live) or covered (final).

   Silent for screen readers on purpose: a score that ticks every minute is
   noise as an announcement, and the strip is plain text anyone can reach.
   Polling stops while the tab is hidden and resumes when it comes back.
   Any failure (offline, ESPN refusing the request) leaves the card exactly
   as the build drew it -- the morning's line and pick. */
(function () {
  var URLS = {
    ncaab: "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=400&dates=",
    ncaaf: "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300&dates="
  };
  var EVERY = 60000;
  var timer = null;

  /* The same rules as ncaab_system.name_key, so a team the build matched
     is matched here too: "SIU-Edwardsville" / "SIU Edwardsville", "Illinois
     St" / "Illinois State" (a leading St is Saint), "Univ." / "University",
     "Miss" / "Mississippi", "Appalachian State" / "App State". */
  var WORDS = { univ: "university", miss: "mississippi" };
  function norm(s) {
    var w = String(s || "").toLowerCase().replace(/&/g, " and ").replace(/-/g, " ")
      .replace(/[^a-z0-9 ]+/g, "").split(/\s+/).filter(Boolean);
    w = w.map(function (x, i) {
      if (x === "st" && i > 0) { return "state"; }
      return WORDS[x] || x;
    });
    return w.join(" ").replace("appalachian state", "app state");
  }

  function etDate(iso) {
    var d = new Date(iso);
    if (isNaN(d)) { return ""; }
    // en-CA formats as YYYY-MM-DD.
    return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" })
      .format(d).replace(/-/g, "");
  }

  function startedCards() {
    var now = Date.now();
    return Array.prototype.filter.call(
      document.querySelectorAll("article[data-sport]"), function (c) {
        var strip = c.querySelector(".cv-res[data-l]");
        var tip = Date.parse(c.getAttribute("data-tip") || "");
        return strip && !isNaN(tip) && tip <= now;
      });
  }

  function verdict(card, away, home, done, L) {
    var side = card.getAttribute("data-side");
    var line = parseFloat(card.getAttribute("data-line"));
    if (!side || isNaN(line)) { return ""; }
    var edge = (side === "home" ? home - away : away - home) + line;
    if (done) {
      if (edge > 0) { return '<b class="won">✓ ' + L[2] + "</b>"; }
      if (edge < 0) { return '<b class="lost">✗ ' + L[3] + "</b>"; }
      return '<b class="push">' + L[4] + "</b>";
    }
    return edge > 0 ? '<b class="won">' + L[5] + "</b>"
                    : '<b class="lost">' + L[6] + "</b>";
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }

  function fill(card, ev) {
    var comp = (ev.competitions || [])[0] || {};
    var sides = {};
    (comp.competitors || []).forEach(function (c) { sides[c.homeAway] = c; });
    if (!sides.home || !sides.away) { return false; }
    var st = ((comp.status || ev.status || {}).type) || {};
    if (st.state === "pre") { return true; }
    var strip = card.querySelector(".cv-res[data-l]");
    var L = (strip.getAttribute("data-l") || "").split("|");
    var away = parseFloat(sides.away.score), home = parseFloat(sides.home.score);
    if (isNaN(away) || isNaN(home)) { return true; }
    // The pick is in the card's order; if ESPN has the clubs the other way
    // round, judge it with the scores swapped.
    var flipped = norm((sides.home.team || {}).displayName) === norm(card.getAttribute("data-away"));
    var cardAway = flipped ? home : away, cardHome = flipped ? away : home;
    var done = st.state === "post" || st.completed === true;
    var label = done ? L[0] : L[1] + " · " + (st.shortDetail || "");
    var an = (sides.away.team || {}).shortDisplayName || card.getAttribute("data-away");
    var hn = (sides.home.team || {}).shortDisplayName || card.getAttribute("data-home");
    strip.innerHTML =
      '<span><span class="st' + (done ? "" : " live") + '">' + esc(label) + "</span>" +
      esc(an) + " " + away + " – " + esc(hn) + " " + home + "</span>" +
      verdict(card, cardAway, cardHome, done, L);
    strip.hidden = false;
    if (done) { strip.removeAttribute("data-l"); }
    return !done;
  }

  function run() {
    timer = null;
    if (document.visibilityState === "hidden") { return; }
    var cards = startedCards();
    if (!cards.length) { return; }
    var groups = {};
    cards.forEach(function (c) {
      var k = c.getAttribute("data-sport") + "|" + etDate(c.getAttribute("data-tip"));
      (groups[k] = groups[k] || []).push(c);
    });
    var pending = Object.keys(groups).map(function (k) {
      var sport = k.split("|")[0], day = k.split("|")[1];
      if (!URLS[sport] || !day) { return Promise.resolve(false); }
      return fetch(URLS[sport] + day).then(function (r) {
        if (!r.ok) { throw new Error(r.status); }
        return r.json();
      }).then(function (data) {
        var byId = {}, byPair = {};
        (data.events || []).forEach(function (ev) {
          byId[ev.id] = ev;
          var comp = (ev.competitions || [])[0] || {};
          var h = "", a = "";
          (comp.competitors || []).forEach(function (c) {
            if (c.homeAway === "home") { h = norm((c.team || {}).displayName); }
            if (c.homeAway === "away") { a = norm((c.team || {}).displayName); }
          });
          // Both orders: the feeds can disagree on who is home.
          byPair[a + "@" + h] = ev;
          byPair[h + "@" + a] = ev;
        });
        var live = false;
        groups[k].forEach(function (c) {
          var ev = byId[c.getAttribute("data-espn")] ||
                   byPair[norm(c.getAttribute("data-away")) + "@" + norm(c.getAttribute("data-home"))];
          if (ev && fill(c, ev)) { live = true; }
        });
        return live;
      }).catch(function () { return false; });
    });
    Promise.all(pending).then(function (states) {
      if (states.some(Boolean)) { timer = setTimeout(run, EVERY); }
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && !timer) { run(); }
  });
  run();
})();

/* Redesign B: Details buttons on the college pick cards, and the
   "Best bets only / All picks" filter. Both are plain buttons whose state is
   in aria-expanded / aria-pressed, so assistive tech hears what they do. */
(function () {
  document.addEventListener("click", function (e) {
    var more = e.target.closest && e.target.closest(".pc-more");
    if (more) {
      var panel = document.getElementById(more.getAttribute("aria-controls"));
      var open = more.getAttribute("aria-expanded") !== "true";
      more.setAttribute("aria-expanded", open ? "true" : "false");
      more.textContent = more.getAttribute(open ? "data-open" : "data-shut");
      if (panel) { panel.hidden = !open; }
      return;
    }
    var f = e.target.closest && e.target.closest(".pc-filter button");
    if (f) {
      var best = f.getAttribute("data-f") === "best";
      f.parentNode.querySelectorAll("button").forEach(function (b) {
        b.setAttribute("aria-pressed", b === f ? "true" : "false");
      });
      document.querySelectorAll(".gcard.pc").forEach(function (c) {
        c.hidden = best && c.getAttribute("data-tier") !== "best";
      });
    }
  });
})();

