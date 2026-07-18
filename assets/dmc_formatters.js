/* Formatadores para gráficos dash-mantine-components (Recharts). */
var dmcfuncs = window.dashMantineFunctions = window.dashMantineFunctions || {};

dmcfuncs.formatNumberPtBR = function (value) {
  if (value === null || value === undefined || value === "") {
    return "";
  }
  var number = Number(value);
  if (Number.isNaN(number)) {
    return String(value);
  }
  return new Intl.NumberFormat("pt-BR", {
    maximumFractionDigits: 1,
  }).format(number);
};

dmcfuncs.formatPercentPtBR = function (value) {
  if (value === null || value === undefined || value === "") {
    return "";
  }
  var number = Number(value);
  if (Number.isNaN(number)) {
    return String(value);
  }
  return (
    new Intl.NumberFormat("pt-BR", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 1,
    }).format(number) + "%"
  );
};

dmcfuncs.formatCurrencyPtBR = function (value) {
  if (value === null || value === undefined || value === "") {
    return "";
  }
  var number = Number(value);
  if (Number.isNaN(number)) {
    return String(value);
  }
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 0,
  }).format(number);
};
