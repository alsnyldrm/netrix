// İlk boyamadan önce kayıtlı veya sistem temasını uygular (CSP: script-src 'self').
(function () {
  var theme = null;
  try {
    theme = localStorage.getItem("netrix-theme");
  } catch (e) {}
  if (theme !== "light" && theme !== "dark")
    theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
})();
