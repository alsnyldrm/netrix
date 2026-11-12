// İlk boyamadan önce kayıtlı görünümü uygular (CSP: script-src 'self').
(function () {
  var theme = null;
  try {
    theme = localStorage.getItem("netrix-theme");
  } catch (e) {}
  if (theme === "system")
    theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.palette = "cobalt";
  document.documentElement.dataset.design = "lumelle";
})();
