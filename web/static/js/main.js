// Vote button: immediate feedback while POST is in flight
document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector(".vote-form");
  if (form) {
    form.addEventListener("submit", (e) => {
      const clicked = e.submitter;
      form.querySelectorAll("button").forEach((btn) => {
        btn.style.pointerEvents = "none";
        if (btn === clicked) {
          btn.textContent = "[ ... ]";
        } else {
          btn.style.opacity = "0.35";
        }
      });
    });
  }
});

// Balken-Animation beim Laden der Ergebnisseite
document.addEventListener("DOMContentLoaded", () => {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) return;

  document.querySelectorAll(".tui-progress.bar-ja, .tui-progress.bar-nein").forEach((el) => {
    const target = el.style.width;
    el.style.width = "0%";
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.style.transition = "width 0.6s ease";
        el.style.width = target;
      });
    });
  });
});
