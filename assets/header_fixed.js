(function () {
  function syncHeaderHeight() {
    var header = document.querySelector(".app-header");
    if (!header) {
      return;
    }
    document.documentElement.style.setProperty(
      "--header-height",
      header.offsetHeight + "px"
    );
  }

  function start() {
    syncHeaderHeight();
    window.addEventListener("resize", syncHeaderHeight);
    if (window.ResizeObserver) {
      var header = document.querySelector(".app-header");
      if (header) {
        new ResizeObserver(syncHeaderHeight).observe(header);
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  // Dash monta o layout depois do primeiro paint.
  var tries = 0;
  var timer = setInterval(function () {
    syncHeaderHeight();
    tries += 1;
    if (document.querySelector(".app-header") && tries > 8) {
      clearInterval(timer);
      start();
    }
    if (tries > 40) {
      clearInterval(timer);
    }
  }, 250);
})();
