/*
 * Verdict filter — progressive enhancement for section hubs.
 * The chips container ships `hidden`; this reveals it and toggles `hidden` on
 * [data-verdict] cards. With JS off, nothing runs and the full feed stands.
 * Vanilla, no deps, < 2KB. State lives in aria-pressed on the buttons.
 */
(function () {
  "use strict";

  var chips = document.querySelector("[data-filter]");
  var feed = document.querySelector("[data-feed]");
  if (!chips || !feed) return;

  var cards = feed.querySelectorAll("[data-verdict]");
  var emptyNote = document.querySelector("[data-feed-empty]");
  var buttons = chips.querySelectorAll("[data-verdict-filter]");

  chips.hidden = false; // reveal now that JS is available

  function apply(active) {
    var shown = 0;
    cards.forEach(function (card) {
      var match = active === "all" || card.getAttribute("data-verdict") === active;
      card.hidden = !match;
      if (match) shown++;
    });
    if (emptyNote) emptyNote.hidden = shown !== 0;
  }

  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      buttons.forEach(function (b) {
        b.setAttribute("aria-pressed", "false");
        b.classList.remove("is-on");
      });
      btn.setAttribute("aria-pressed", "true");
      btn.classList.add("is-on");
      apply(btn.getAttribute("data-verdict-filter"));
    });
  });
})();
