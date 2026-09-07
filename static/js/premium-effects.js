// Efeito de glow que segue o cursor nos cards de módulo/superfície.
// Puramente cosmético: define --mx/--my (usadas em premium-effects.css)
// via custom properties, sem alterar nenhuma lógica existente.
(function () {
  function ligarGlow(seletor) {
    document.querySelectorAll(seletor).forEach(function (el) {
      el.addEventListener("mousemove", function (e) {
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", ((e.clientX - r.left) / r.width) * 100 + "%");
        el.style.setProperty("--my", ((e.clientY - r.top) / r.height) * 100 + "%");
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    ligarGlow(".card-modulo");
  });
})();
