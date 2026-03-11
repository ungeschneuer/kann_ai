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
