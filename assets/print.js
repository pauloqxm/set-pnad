(function () {
  function resizeCharts() {
    if (!window.Plotly) {
      return;
    }
    document.querySelectorAll(".js-plotly-plot").forEach(function (el) {
      try {
        Plotly.Plots.resize(el);
      } catch (e) {
        /* gráfico ainda não montado */
      }
    });
  }

  window.addEventListener("beforeprint", resizeCharts);

  if (window.matchMedia) {
    window.matchMedia("print").addEventListener("change", function (mql) {
      if (mql.matches) {
        resizeCharts();
      }
    });
  }
})();
