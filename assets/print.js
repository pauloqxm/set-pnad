(function () {
  var PRINT_CHART_HEIGHT = 230;

  function resizeCharts() {
    if (!window.Plotly) {
      return;
    }
    var isPrint = window.matchMedia && window.matchMedia("print").matches;
    document.querySelectorAll(".js-plotly-plot").forEach(function (el) {
      try {
        if (isPrint && el.closest(".print-cols-2")) {
          Plotly.relayout(el, { height: PRINT_CHART_HEIGHT, autosize: true });
        }
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
