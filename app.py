"""Dashboard analítico da PNAD Contínua no Ceará — 1º trimestre de 2026.

Interface construída com dash-mantine-components (gráficos Recharts) e
dash-ag-grid, organizada como um roteiro de análise: indicadores gerais,
condição de ocupação, posição na ocupação, setores, rendimento,
subutilização e leitura geral, sempre destacando a significância
estatística (setas do IBGE) das variações trimestral e interanual.
"""

from __future__ import annotations

from pathlib import Path

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback, ctx, dcc, html, no_update

import data_update

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "data" / "pnad_ce_1tri2026.csv"
COMPARE_CSV = BASE_DIR / "data" / "pnad_comparativo_1tri2026.csv"
SERIES_CSV = BASE_DIR / "data" / "pnad_ce_serie.csv"
LATEST = "jan-fev-mar/2026"
GEO_ORDER = (
    "Brasil",
    "Nordeste",
    "Maranhão",
    "Piauí",
    "Ceará",
    "Rio Grande do Norte",
    "Paraíba",
    "Pernambuco",
    "Alagoas",
    "Sergipe",
    "Bahia",
)
COMPARE_INDICATORS = [
    "Taxa de desocupação",
    "Nível da ocupação",
    "Taxa de participação na força de trabalho",
    "Ocupadas",
    "Desocupadas",
    "Rendimento médio mensal real habitual",
    "Taxa composta de subutilização da força de trabalho",
]

if not CSV_PATH.exists():
    raise FileNotFoundError(
        f"Base não encontrada em {CSV_PATH}. Execute primeiro: python extract_data.py"
    )
if not COMPARE_CSV.exists():
    raise FileNotFoundError(
        f"Base comparativa não encontrada em {COMPARE_CSV}. Execute: python extract_regional.py"
    )
if not SERIES_CSV.exists():
    raise FileNotFoundError(
        f"Série temporal não encontrada em {SERIES_CSV}. Execute: python extract_series.py"
    )

df = pd.read_csv(CSV_PATH)
df_cmp = pd.read_csv(COMPARE_CSV)
df_serie = pd.read_csv(SERIES_CSV).sort_values("ordem_periodo")
PERIOD_ORDER = df_serie["periodo"].drop_duplicates().tolist()
DETAIL_PERIOD_ORDER = (
    df.sort_values("ordem_periodo")["periodo"].drop_duplicates().tolist()
)
# KPIs e análise detalhada usam o CSV curado; a série pode ter outros trimestres.
LATEST = DETAIL_PERIOD_ORDER[-1] if DETAIL_PERIOD_ORDER else PERIOD_ORDER[-1]
PREVIOUS_PERIODS = [p for p in PERIOD_ORDER if p != LATEST][-3:]


def reload_runtime_data() -> None:
    """Recarrega CSVs em memória após upload (série e comparativo)."""
    global df, df_cmp, df_serie, PERIOD_ORDER, DETAIL_PERIOD_ORDER, LATEST, PREVIOUS_PERIODS
    df = pd.read_csv(CSV_PATH)
    df_cmp = pd.read_csv(COMPARE_CSV)
    df_serie = pd.read_csv(SERIES_CSV).sort_values("ordem_periodo")
    PERIOD_ORDER = df_serie["periodo"].drop_duplicates().tolist()
    DETAIL_PERIOD_ORDER = (
        df.sort_values("ordem_periodo")["periodo"].drop_duplicates().tolist()
    )
    LATEST = DETAIL_PERIOD_ORDER[-1] if DETAIL_PERIOD_ORDER else PERIOD_ORDER[-1]
    PREVIOUS_PERIODS = [p for p in PERIOD_ORDER if p != LATEST][-3:]


SIG_LABEL = {"cresceu": "cresceu", "decresceu": "decresceu", "estavel": "estável"}
SIG_COLOR = {"cresceu": "teal", "decresceu": "red", "estavel": "gray"}
SIG_ARROW = {"cresceu": "↑", "decresceu": "↓", "estavel": "→"}


def br(number: float, decimals: int = 1) -> str:
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "@").replace(".", ",").replace("@", ".")


def latest_row(indicator: str, section: str) -> pd.Series:
    rows = df[(df["secao"] == section) & (df["indicador"] == indicator)]
    if rows.empty:
        raise ValueError(f"Indicador não encontrado: {section} / {indicator}")
    preferred = rows[rows["periodo"] == LATEST]
    if not preferred.empty:
        return preferred.iloc[0]
    return rows.sort_values("ordem_periodo").iloc[-1]


def series_values(indicator: str, section: str) -> list[float]:
    rows = df[(df["secao"] == section) & (df["indicador"] == indicator)]
    values: list[float] = []
    for period in DETAIL_PERIOD_ORDER:
        match = rows[rows["periodo"] == period]
        if match.empty:
            continue
        values.append(float(match["valor"].iloc[0]))
    return values


def delta_text(row: pd.Series, scope: str) -> str:
    if row["unidade"] == "%":
        value = row[f"variacao_{scope}_abs"]
        return f"{'+' if value >= 0 else ''}{br(value)} p.p."
    pct = row[f"variacao_{scope}_pct"]
    return f"{'+' if pct >= 0 else ''}{br(pct)}%"


def sig_badge(row: pd.Series, scope: str, label: str) -> dmc.Badge:
    situ = row[f"situacao_{scope}"]
    return dmc.Badge(
        f"{SIG_ARROW[situ]} {delta_text(row, scope)} {label}",
        color=SIG_COLOR[situ],
        variant="light",
        radius="sm",
        size="lg",
        styles={"label": {"textTransform": "none"}},
    )


def people(value: float) -> float:
    """Converte estimativa em mil pessoas para o número absoluto."""
    return value * 1000


def display_value(value: float, unit: str) -> float:
    if unit == "Mil pessoas":
        return people(value)
    if unit == "R$ milhões":
        return value * 1_000_000
    return value


def value_text(row: pd.Series) -> str:
    value, unit = row["valor"], row["unidade"]
    if unit == "%":
        return f"{br(value)}%"
    if unit == "R$":
        return f"R$ {br(value, 0)}"
    if unit == "R$ milhões":
        return f"R$ {br(display_value(value, unit), 0)}"
    if unit == "Mil pessoas":
        return br(display_value(value, unit), 0)
    return br(value, 0)


def compare_scale(unit: str) -> float:
    if unit == "Mil pessoas":
        return 1000
    if unit == "R$ milhões":
        return 1_000_000
    return 1


def compare_display_value(value: float, unit: str) -> float:
    return float(value) * compare_scale(unit)


def compare_value_label(value: float, unit: str) -> str:
    if unit == "%":
        return f"{br(value)}%"
    if unit == "R$":
        return f"R$ {br(value, 0)}"
    if unit == "R$ milhões":
        return f"R$ {br(compare_display_value(value, unit), 0)}"
    if unit == "Mil pessoas":
        return br(compare_display_value(value, unit), 0)
    return br(value, 0)


def compare_bar_color(geografia: str, *, total: bool = False) -> str:
    if total:
        if geografia == "Ceará":
            return "#9BB8D4"
        if geografia in {"Brasil", "Nordeste"}:
            return "#B7BEC8"
        return "#D5DEE8"
    if geografia == "Ceará":
        return "#005CA9"
    if geografia in {"Brasil", "Nordeste"}:
        return "#687386"
    return "#74A7D4"


def compare_ordered_geos(subset: pd.DataFrame) -> list[str]:
    """Brasil e Nordeste no topo; demais estados em ordem decrescente do valor."""
    rows = [
        {
            "geografia": row["geografia"],
            "valor": float(row["valor"]),
        }
        for _, row in subset.iterrows()
    ]
    pinned = [item for item in rows if item["geografia"] in {"Brasil", "Nordeste"}]
    pinned.sort(key=lambda item: 0 if item["geografia"] == "Brasil" else 1)
    states = sorted(
        [item for item in rows if item["geografia"] not in {"Brasil", "Nordeste"}],
        key=lambda item: item["valor"],
        reverse=True,
    )
    # Plotly desenha de baixo para cima: inverter para Brasil/Nordeste no topo.
    return [item["geografia"] for item in reversed(pinned + states)]


def compare_series_values(
    indicator: str, geos: list[str]
) -> tuple[list[float | int], list[str], str]:
    subset = df_cmp[df_cmp["indicador"] == indicator].set_index("geografia")
    unit = subset["unidade"].iloc[0]
    scale = compare_scale(unit)
    values: list[float | int] = []
    labels: list[str] = []
    for geo in geos:
        raw = float(subset.loc[geo, "valor"])
        value = raw * scale
        values.append(round(value, 1) if unit == "%" else int(round(value)))
        labels.append(compare_value_label(raw, unit))
    return values, labels, unit


def compare_chart(indicator: str, hidden_geos: list[str] | None = None) -> dcc.Graph:
    subset = df_cmp[df_cmp["indicador"] == indicator].copy()
    hidden = set(hidden_geos or [])
    geos = [geo for geo in compare_ordered_geos(subset) if geo not in hidden]
    if not geos:
        empty = go.Figure()
        empty.update_layout(
            template="plotly_white",
            height=280,
            margin={"l": 40, "r": 40, "t": 20, "b": 20},
            xaxis={"visible": False},
            yaxis={"visible": False},
            annotations=[
                {
                    "text": "Nenhuma geografia visível. Use “Mostrar todos”.",
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                    "font": {"size": 14, "color": "#687386"},
                }
            ],
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        return dcc.Graph(
            id="compare-chart",
            figure=empty,
            config={"displayModeBar": False},
            style={"width": "100%"},
        )

    values, labels, unit = compare_series_values(indicator, geos)
    with_total = indicator in {"Ocupadas", "Desocupadas"}

    figure = go.Figure()
    max_value = max(values) if values else 1

    if with_total:
        total_values, total_labels, _ = compare_series_values(
            "Pessoas de 14 anos ou mais", geos
        )
        remainders = [
            max(0, int(total) - int(part))
            for part, total in zip(values, total_values, strict=True)
        ]
        percents = [
            (100.0 * float(part) / float(total)) if float(total) else 0.0
            for part, total in zip(values, total_values, strict=True)
        ]
        percent_labels = [f"{br(pct)}%" for pct in percents]
        end_labels = [
            f"{part} ({pct})  ·  total {total}"
            for part, pct, total in zip(labels, percent_labels, total_labels, strict=True)
        ]
        # Parte destacada (ocupadas/desocupadas) à esquerda; o restante
        # completa até a quantidade total — barra empilhada horizontal.
        figure.add_trace(
            go.Bar(
                name=indicator,
                y=geos,
                x=values,
                orientation="h",
                textposition="none",
                cliponaxis=False,
                marker={
                    "color": [compare_bar_color(geo) for geo in geos],
                    "line": {"width": 0},
                },
                hovertemplate=(
                    "%{y}<br>"
                    + indicator
                    + ": %{customdata[0]} (%{customdata[1]})<br>Total (14+): %{customdata[2]}"
                    "<br><i>Clique para ocultar</i><extra></extra>"
                ),
                customdata=[
                    [part, pct, total]
                    for part, pct, total in zip(labels, percent_labels, total_labels, strict=True)
                ],
            )
        )
        figure.add_trace(
            go.Bar(
                name="Demais pessoas de 14 anos ou mais",
                y=geos,
                x=remainders,
                orientation="h",
                text=end_labels,
                textposition="outside",
                cliponaxis=False,
                marker={
                    "color": [compare_bar_color(geo, total=True) for geo in geos],
                    "line": {"width": 0},
                    "cornerradius": 6,
                },
                hovertemplate=(
                    "%{y}<br>Demais (até o total 14+): %{x:,.0f}"
                    "<br>Total (14+): %{customdata[1]}"
                    "<br>Participação: %{customdata[0]}"
                    "<br><i>Clique para ocultar</i><extra></extra>"
                ),
                customdata=[
                    [pct, total] for pct, total in zip(percent_labels, total_labels, strict=True)
                ],
            )
        )
        max_value = max(total_values) if total_values else 1
    else:
        figure.add_trace(
            go.Bar(
                name=indicator,
                y=geos,
                x=values,
                orientation="h",
                text=labels,
                textposition="outside",
                cliponaxis=False,
                marker={
                    "color": [compare_bar_color(geo) for geo in geos],
                    "line": {"width": 0},
                },
                hovertemplate="%{y}<br>%{text}<br><i>Clique para ocultar</i><extra></extra>",
            )
        )

    if unit == "%":
        tick_values = [0, 20, 40, 60, 80]
        tick_values = [tick for tick in tick_values if tick <= max(80, max_value * 1.1)]
        tick_text = [f"{tick}" for tick in tick_values]
    else:
        step = 10 ** max(0, len(str(int(max_value))) - 1)
        tick_values = list(range(0, int(max_value * 1.15) + step, step))
        if len(tick_values) > 6:
            step *= 2
            tick_values = list(range(0, int(max_value * 1.15) + step, step))
        tick_text = [br(tick, 0) for tick in tick_values]

    figure.update_layout(
        template="plotly_white",
        barmode="stack" if with_total else "relative",
        bargap=0.35,
        height=max(320, 48 * len(geos) + (110 if with_total else 80)),
        margin={"l": 140, "r": 240 if with_total else 150, "t": 20, "b": 40},
        xaxis={
            "title": None,
            "tickmode": "array",
            "tickvals": tick_values,
            "ticktext": tick_text,
            "gridcolor": "#E6EBF0",
            "zeroline": False,
            "range": [0, max_value * (1.42 if with_total else 1.22)],
        },
        yaxis={"title": None, "automargin": True},
        font={"family": "Inter, Segoe UI, Arial, sans-serif", "color": "#25324A", "size": 13},
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=with_total,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "itemclick": "toggle",
            "itemdoubleclick": "toggleothers",
        }
        if with_total
        else None,
        clickmode="event+select",
    )

    return dcc.Graph(
        id="compare-chart",
        figure=figure,
        config={"displayModeBar": False},
        style={"width": "100%"},
    )


def compare_summary_card(title: str, indicator: str) -> dmc.Card:
    rows = {
        geo: df_cmp[(df_cmp["geografia"] == geo) & (df_cmp["indicador"] == indicator)].iloc[0]
        for geo in ("Ceará", "Brasil", "Nordeste")
    }
    unit = rows["Ceará"]["unidade"]
    return dmc.Card(
        withBorder=True,
        radius="md",
        padding="lg",
        children=[
            dmc.Text(title, size="sm", c="dimmed", fw=600),
            dmc.Group(
                justify="space-between",
                mt="sm",
                children=[
                    dmc.Stack(
                        gap=2,
                        children=[
                            dmc.Text("Ceará", size="xs", c="blue", fw=700),
                            dmc.Text(compare_value_label(rows["Ceará"]["valor"], unit), fw=700),
                        ],
                    ),
                    dmc.Stack(
                        gap=2,
                        children=[
                            dmc.Text("Brasil", size="xs", c="dimmed"),
                            dmc.Text(compare_value_label(rows["Brasil"]["valor"], unit), size="sm"),
                        ],
                    ),
                    dmc.Stack(
                        gap=2,
                        children=[
                            dmc.Text("Nordeste", size="xs", c="dimmed"),
                            dmc.Text(compare_value_label(rows["Nordeste"]["valor"], unit), size="sm"),
                        ],
                    ),
                ],
            ),
        ],
    )


def year_ago_period(period: str = LATEST) -> str | None:
    if "/" not in period:
        return None
    label, year = period.rsplit("/", 1)
    try:
        return f"{label}/{int(year) - 1}"
    except ValueError:
        return None


def period_row(indicator: str, section: str, period: str) -> pd.Series | None:
    rows = df[
        (df["secao"] == section)
        & (df["indicador"] == indicator)
        & (df["periodo"] == period)
    ]
    if rows.empty:
        return None
    return rows.iloc[0]


def short_tri_label(period: str) -> str:
    quarter = {
        "jan-fev-mar": "1º tri",
        "abr-mai-jun": "2º tri",
        "jul-ago-set": "3º tri",
        "out-nov-dez": "4º tri",
    }
    if "/" not in period:
        return period
    label, year = period.rsplit("/", 1)
    return f"{quarter.get(label, label)}/{year}"


def kpi_card(indicator: str, section: str, description: str) -> dmc.Card:
    row = latest_row(indicator, section)
    current_period = str(row["periodo"])
    prev_period = year_ago_period(current_period)
    prev_row = period_row(indicator, section, prev_period) if prev_period else None
    accent = {"cresceu": "#0B7285", "decresceu": "#C92A2A", "estavel": "#005CA9"}.get(
        row["situacao_anual"], "#005CA9"
    )

    value_block = [
        dmc.Text(
            value_text(row),
            fw=800,
            style={"fontSize": "1.85rem", "lineHeight": 1.05, "color": "#0B1F33", "letterSpacing": "-0.02em"},
        ),
    ]
    if prev_row is not None:
        value_block.append(
            dmc.Group(
                gap=6,
                align="center",
                mt=6,
                children=[
                    dmc.Text(
                        value_text(prev_row),
                        size="sm",
                        fw=700,
                        c="gray.7",
                        style={"fontSize": "0.95rem"},
                    ),
                    dmc.Text(
                        f"mesmo tri. {short_tri_label(prev_period)}",
                        size="xs",
                        c="dimmed",
                    ),
                ],
            )
        )

    return dmc.Card(
        className="kpi-card",
        withBorder=True,
        radius="md",
        padding="lg",
        style={"borderLeft": f"4px solid {accent}"},
        children=[
            dmc.Text(
                indicator,
                size="xs",
                c="dimmed",
                fw=700,
                tt="uppercase",
                style={"letterSpacing": "0.04em"},
            ),
            dmc.Stack(gap=0, mt=8, mb=8, children=value_block),
            dmc.Text(description, size="xs", c="dimmed", mb="md"),
            dmc.Group(
                [sig_badge(row, "trimestral", "no tri."), sig_badge(row, "anual", "no ano")],
                gap="xs",
            ),
        ],
    )


def series_scale(unit: str) -> float:
    if unit == "Mil pessoas":
        return 1000
    if unit == "R$ milhões":
        return 1_000_000
    return 1


def series_chart_data(indicators: list[str], scale: float = 1.0) -> list[dict]:
    data = []
    for period in PERIOD_ORDER:
        entry: dict = {"periodo": period}
        for indicator in indicators:
            rows = df_serie[
                (df_serie["indicador"] == indicator) & (df_serie["periodo"] == period)
            ]
            if rows.empty:
                continue
            entry[indicator] = float(rows["valor"].iloc[0]) * scale
        data.append(entry)
    return data


def series_line_chart(indicators: list[str], title: str, unit: str) -> dcc.Graph:
    """Linha do trimestre atual + 3 anteriores, com rótulos formatados."""
    scale = series_scale(unit)
    figure = go.Figure()
    colors = ["#005CA9", "#E67700", "#0B7285", "#9C36B5", "#C92A2A"]

    for index, indicator in enumerate(indicators):
        rows = df_serie[df_serie["indicador"] == indicator].sort_values("ordem_periodo")
        if rows.empty:
            continue
        values = [float(v) * scale for v in rows["valor"]]
        if unit == "%":
            labels = [f"{br(v)}%" for v in rows["valor"]]
        elif unit == "R$":
            labels = [f"R$ {br(v, 0)}" for v in rows["valor"]]
        elif unit == "R$ milhões":
            labels = [f"R$ {br(v * 1_000_000, 0)}" for v in rows["valor"]]
        else:
            labels = [br(v * scale, 0) for v in rows["valor"]]

        figure.add_trace(
            go.Scatter(
                x=rows["periodo"].tolist(),
                y=values,
                mode="lines+markers+text",
                name=indicator,
                text=labels,
                textposition="top center",
                line={"width": 3, "color": colors[index % len(colors)]},
                marker={"size": 9},
                hovertemplate="%{x}<br>%{text}<extra>" + indicator + "</extra>",
            )
        )

    figure.update_layout(
        title={"text": title, "x": 0, "font": {"size": 15}},
        template="plotly_white",
        height=340,
        margin={"l": 50, "r": 30, "t": 50, "b": 50},
        legend={"orientation": "h", "y": -0.22, "x": 0},
        xaxis={"title": None, "type": "category"},
        yaxis={"title": None, "gridcolor": "#E6EBF0", "zeroline": False},
        font={"family": "Inter, Segoe UI, Arial, sans-serif", "color": "#25324A", "size": 12},
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    return dcc.Graph(figure=figure, config={"displayModeBar": False})


def quarters_chart_data(
    indicators: list[str],
    section: str | None = None,
    scale: float = 1.0,
) -> list[dict]:
    """Mantém compatibilidade: prioriza série multi-PDF quando o indicador existir nela."""
    available = set(df_serie["indicador"])
    if all(indicator in available for indicator in indicators):
        return series_chart_data(indicators, scale=scale)

    data = []
    for period in PERIOD_ORDER:
        # Fallback para a base detalhada do trimestre atual (quando aplicável).
        if period not in set(df["periodo"].astype(str)):
            continue
        entry: dict = {"periodo": period}
        for indicator in indicators:
            query = (df["indicador"] == indicator) & (df["periodo"] == period)
            if section:
                query &= df["secao"] == section
            rows = df[query]
            if rows.empty:
                continue
            entry[indicator] = float(rows["valor"].iloc[0]) * scale
        data.append(entry)
    return data


PALETTE = ["blue.6", "orange.6", "teal.6", "grape.6", "cyan.6", "red.6"]


def line_chart(
    indicators: list[str],
    section: str,
    unit: str,
    height: int = 300,
    scale: float = 1.0,
) -> dmc.LineChart | dcc.Graph:
    if all(indicator in set(df_serie["indicador"]) for indicator in indicators):
        return series_line_chart(
            indicators,
            title=f"{' · '.join(indicators[:2])}{'…' if len(indicators) > 2 else ''}",
            unit=unit if scale == 1 else ("pessoas" if unit == "Mil pessoas" else unit),
        )
    return dmc.LineChart(
        h=height,
        data=quarters_chart_data(indicators, section, scale=scale),
        dataKey="periodo",
        series=[
            {"name": name, "color": PALETTE[i % len(PALETTE)]}
            for i, name in enumerate(indicators)
        ],
        curveType="linear",
        withLegend=True,
        legendProps={"verticalAlign": "bottom"},
        unit=unit,
        withDots=True,
        strokeWidth=2.5,
        gridAxis="xy",
        withXAxis=True,
        withYAxis=True,
        yAxisProps={"domain": ["auto", "auto"], "width": 90},
    )


def grouped_bar_chart(
    indicators: list[str],
    section: str,
    unit: str,
    height: int = 320,
    scale: float = 1.0,
) -> dmc.BarChart:
    return dmc.BarChart(
        h=height,
        data=quarters_chart_data(indicators, section, scale=scale),
        dataKey="periodo",
        series=[
            {"name": name, "color": PALETTE[i % len(PALETTE)]}
            for i, name in enumerate(indicators)
        ],
        withLegend=True,
        legendProps={"verticalAlign": "bottom"},
        unit=unit,
        gridAxis="y",
        yAxisProps={"width": 90},
    )


def variation_bar_chart(section: str, scope: str, unit_filter: str = "Mil pessoas") -> dmc.BarChart:
    """Barras horizontais da variação percentual, separando altas e quedas."""
    subset = df[
        (df["secao"] == section)
        & (df["periodo"] == LATEST)
        & (df["unidade"] == unit_filter)
    ].copy()
    column = f"variacao_{scope}_pct"
    subset = subset.sort_values(column)
    data = []
    for _, row in subset.iterrows():
        significant = row[f"situacao_{scope}"] != "estavel"
        name = row["indicador"] + (" *" if significant else "")
        value = float(row[column])
        data.append(
            {
                "indicador": name,
                "Alta": value if value >= 0 else None,
                "Queda": value if value < 0 else None,
            }
        )
    return dmc.BarChart(
        h=max(300, 34 * len(data) + 70),
        data=data,
        dataKey="indicador",
        orientation="vertical",
        type="stacked",
        series=[
            {"name": "Queda", "color": "red.6"},
            {"name": "Alta", "color": "teal.6"},
        ],
        unit="%",
        withLegend=False,
        gridAxis="x",
        yAxisProps={"width": 320},
        barProps={"radius": 3},
    )


def narrative(children) -> dmc.Alert:
    return dmc.Alert(children, color="blue", variant="light", radius="md")


def section_title(number: str, text: str) -> dmc.Group:
    return dmc.Group(
        [
            dmc.Badge(number, size="lg", radius="sm", variant="filled", color="blue"),
            dmc.Title(text, order=3),
        ],
        gap="sm",
        mt="xl",
        mb="sm",
    )


def sig_legend() -> dmc.Group:
    return dmc.Group(
        [
            dmc.Badge("↑ cresceu (significativo)", color="teal", variant="light",
                      styles={"label": {"textTransform": "none"}}),
            dmc.Badge("↓ decresceu (significativo)", color="red", variant="light",
                      styles={"label": {"textTransform": "none"}}),
            dmc.Badge("→ estável (dentro da margem de erro)", color="gray", variant="light",
                      styles={"label": {"textTransform": "none"}}),
        ],
        gap="xs",
    )


app = Dash(
    __name__,
    title="PNAD Ceará — 1º tri 2026",
    external_stylesheets=dmc.styles.ALL,
    suppress_callback_exceptions=True,
)

server = app.server

header = dmc.Paper(
    radius=0,
    p="xl",
    style={"backgroundColor": "#123b66", "color": "white"},
    children=dmc.Container(
        size="xl",
        children=dmc.Group(
            justify="space-between",
            align="flex-end",
            children=[
                dmc.Stack(
                    gap=4,
                    children=[
                        dmc.Text("MERCADO DE TRABALHO", size="xs", fw=800,
                                 style={"letterSpacing": "0.15em", "color": "#b8d7ef"}),
                        dmc.Title("PNAD Contínua — Ceará", order=1, style={"color": "white"}),
                        dmc.Text(
                            f"Trimestre atual: {LATEST} · comparação com os 3 trimestres anteriores",
                            style={"color": "#d7e7f3"},
                        ),
                    ],
                ),
                dmc.Badge("Fonte: IBGE · pasta pnad/", size="lg", variant="white",
                          color="blue", styles={"label": {"textTransform": "none"}}),
            ],
        ),
    ),
)

how_to_read = dmc.Card(
    withBorder=True,
    radius="md",
    padding="lg",
    mt="xl",
    children=[
        dmc.Title("Como ler os dados", order=4, mb="xs"),
        dmc.Text(
            f"A análise usa os quadros sintéticos da pasta pnad/. O trimestre atual é {LATEST}; "
            f"os gráficos de linha comparam esse resultado com {', '.join(PREVIOUS_PERIODS)}. "
            "Nas tabelas do trimestre atual, a variação trimestral e a interanual trazem também "
            "a situação estatística do IBGE (cresceu, decresceu ou estável).",
            size="sm",
            c="dimmed",
            mb="sm",
        ),
        sig_legend(),
    ],
)

kpis = dmc.SimpleGrid(
    cols={"base": 1, "sm": 2, "lg": 4},
    spacing="md",
    mt="xl",
    children=[
        kpi_card("Taxa de desocupação", "Mercado de trabalho", "Percentual de desocupados na força de trabalho"),
        kpi_card("Ocupadas", "Mercado de trabalho", "Pessoas de 14 anos ou mais trabalhando"),
        kpi_card("Desocupadas", "Mercado de trabalho", "Pessoas em busca de trabalho"),
        kpi_card("Rendimento médio mensal real habitual", "Rendimento", "Todos os trabalhos, valores reais"),
    ],
)

section1 = dmc.Stack(
    gap="md",
    children=[
        section_title("1", "Indicadores gerais do mercado de trabalho"),
        narrative([
            dmc.Text([
                "A taxa de desocupação foi de 8,0% → 5,0% → 7,3%: ",
                dmc.Text("alta significativa de 2,3 p.p. sobre out-dez/2025", fw=700, span=True),
                " — efeito sazonal típico da passagem do 4º para o 1º trimestre —, mas ",
                dmc.Text("estável na comparação anual (-0,7 p.p.)", fw=700, span=True),
                ", o melhor resultado para um 1º trimestre desde 2012. O nível da ocupação caiu de "
                "forma significativa no trimestre (-2,0 p.p., para 47,6%), e a participação na força "
                "de trabalho ficou estável (51,3%).",
            ], size="sm"),
        ]),
        dmc.Card(
            withBorder=True, radius="md", padding="lg",
            children=[
                dmc.Text("Taxas principais (%) — atual e 3 trimestres anteriores", fw=600, mb="sm"),
                line_chart(
                    ["Taxa de desocupação", "Nível da ocupação",
                     "Taxa de participação na força de trabalho"],
                    "Mercado de trabalho", "%",
                ),
            ],
        ),
    ],
)

section2 = dmc.Stack(
    gap="md",
    children=[
        section_title("2", "População por condição de ocupação"),
        narrative(
            dmc.Text([
                "Os ocupados caíram de 3.756.000 para 3.603.000 (",
                dmc.Text("-153.000, -4,1%, queda significativa no trimestre", fw=700, span=True),
                "); na comparação anual, ficaram estáveis (+84.000). Os desocupados subiram de "
                "196.000 para 282.000 (",
                dmc.Text("+86.000, +44,2% no trimestre — alta significativa", fw=700, span=True),
                "). A população fora da força de trabalho ficou estável (3.692.000): quem perdeu "
                "ocupação migrou para a desocupação, não para fora do mercado.",
            ], size="sm"),
        ),
        dmc.Card(
            withBorder=True, radius="md", padding="lg",
            children=[
                dmc.Text("Pessoas de 14 anos ou mais — atual e 3 trimestres anteriores", fw=600, mb="sm"),
                grouped_bar_chart(
                    ["Ocupadas", "Desocupadas", "Fora da força de trabalho"],
                    "Mercado de trabalho", "", scale=1000,
                ),
            ],
        ),
    ],
)

section3 = dmc.Stack(
    gap="md",
    children=[
        section_title("3", "Ocupados por posição na ocupação"),
        narrative(
            dmc.Text([
                "O destaque é a formalização: empregados do setor privado com carteira subiram de "
                "940.000 para 1.037.000 no ano (",
                dmc.Text("+96.000, +10,2%, alta significativa", fw=700, span=True),
                "), e o setor público cresceu +71.000 (+14,3%), puxado pelos vínculos sem carteira "
                "(+38,9%). Na direção oposta, o trabalho doméstico sem carteira caiu -14,2% no ano (",
                dmc.Text("queda significativa nas duas janelas", fw=700, span=True),
                ") e os empregadores sem CNPJ recuaram -33,8% — encolhimento de pequenos negócios "
                "informais. Conta própria caiu -5,6% no trimestre (significativo), mas está estável "
                "no ano.",
            ], size="sm"),
        ),
        dmc.Card(
            withBorder=True, radius="md", padding="lg",
            children=[
                dmc.Group(justify="space-between", children=[
                    dmc.Text("Variação anual (%) por posição e categoria", fw=600),
                    dmc.Text("* variação estatisticamente significativa", size="xs", c="dimmed"),
                ], mb="sm"),
                variation_bar_chart("Ocupação", "anual"),
            ],
        ),
    ],
)

section4 = dmc.Stack(
    gap="md",
    children=[
        section_title("4", "Ocupados por setor de atividade"),
        narrative(
            dmc.Text([
                "No trimestre, as quedas significativas vieram da agropecuária (-8,6%), da indústria "
                "geral (-10,5%) e dos serviços domésticos (-14,1%). Na comparação anual, os setores "
                "que sustentaram a ocupação foram ",
                dmc.Text(
                    "administração pública, educação e saúde (+101.000, +15,4%) e informação, "
                    "finanças e atividades profissionais (+62.000, +20,7%)",
                    fw=700, span=True,
                ),
                " — ambos com alta significativa. Comércio, agropecuária e indústria acumulam quedas "
                "anuais, mas classificadas como estáveis pelo teste estatístico.",
            ], size="sm"),
        ),
        dmc.Card(
            withBorder=True, radius="md", padding="lg",
            children=[
                dmc.Tabs(
                    value="anual",
                    children=[
                        dmc.TabsList([
                            dmc.TabsTab("Variação anual", value="anual"),
                            dmc.TabsTab("Variação trimestral", value="trimestral"),
                        ]),
                        dmc.TabsPanel(
                            dmc.Stack([
                                dmc.Text("* variação estatisticamente significativa",
                                         size="xs", c="dimmed", mt="sm"),
                                variation_bar_chart("Atividades", "anual"),
                            ]),
                            value="anual",
                        ),
                        dmc.TabsPanel(
                            dmc.Stack([
                                dmc.Text("* variação estatisticamente significativa",
                                         size="xs", c="dimmed", mt="sm"),
                                variation_bar_chart("Atividades", "trimestral"),
                            ]),
                            value="trimestral",
                        ),
                    ],
                ),
            ],
        ),
    ],
)

section5 = dmc.Stack(
    gap="md",
    children=[
        section_title("5", "Rendimento"),
        narrative(
            dmc.Text([
                "O rendimento médio real habitual subiu de R$ 2.333 para R$ 2.597 (",
                dmc.Text("+11,4% no ano, alta significativa", fw=700, span=True),
                "; estável no trimestre, +5,2%). A massa de rendimento — soma de tudo que é pago aos "
                "ocupados — chegou a R$ 9.235.000.000 (",
                dmc.Text("+13,9% no ano, também significativo", fw=700, span=True),
                "), combinando mais gente formalizada e rendimento médio maior.",
            ], size="sm"),
        ),
        dmc.SimpleGrid(
            cols={"base": 1, "md": 2},
            spacing="md",
            children=[
                dmc.Card(
                    withBorder=True, radius="md", padding="lg",
                    children=[
                        dmc.Text("Rendimento médio real habitual (R$)", fw=600, mb="sm"),
                        grouped_bar_chart(
                            ["Rendimento médio mensal real habitual"], "Rendimento", "", 280,
                        ),
                    ],
                ),
                dmc.Card(
                    withBorder=True, radius="md", padding="lg",
                    children=[
                        dmc.Text("Massa de rendimento (R$)", fw=600, mb="sm"),
                        grouped_bar_chart(
                            ["Massa de rendimento mensal real habitual"],
                            "Rendimento", "", 280, scale=1_000_000,
                        ),
                    ],
                ),
            ],
        ),
    ],
)

section6 = dmc.Stack(
    gap="md",
    children=[
        section_title("6", "Subutilização da força de trabalho"),
        narrative(
            dmc.Text([
                "Os indicadores ampliados de desemprego mostram os dois movimentos ao mesmo tempo: "
                "a taxa composta de subutilização subiu de 17,4% para 19,8% no trimestre (",
                dmc.Text("+2,4 p.p., alta significativa", fw=700, span=True),
                "), mas caiu 3,8 p.p. na comparação anual (",
                dmc.Text("queda significativa", fw=700, span=True),
                "). As pessoas desalentadas subiram para 219.000 no trimestre (+16,9%), porém estão "
                "25,4% abaixo de um ano atrás. A subocupação por insuficiência de horas caiu nas "
                "duas janelas (-15,2% no trimestre e -20,6% no ano).",
            ], size="sm"),
        ),
        dmc.Card(
            withBorder=True, radius="md", padding="lg",
            children=[
                dmc.Text("Taxas de subutilização (%) — atual e 3 trimestres anteriores", fw=600, mb="sm"),
                line_chart(
                    [
                        "Taxa composta de subutilização da força de trabalho",
                        "Taxa de desocupação",
                        "Percentual de pessoas desalentadas",
                    ],
                    "Subutilização", "%", 340,
                ),
            ],
        ),
    ],
)

reading = dmc.Card(
    withBorder=True,
    radius="md",
    padding="xl",
    mt="xl",
    style={"borderLeft": "4px solid var(--mantine-color-blue-6)"},
    children=[
        dmc.Title("Leitura geral", order=3, mb="sm"),
        dmc.Text(
            "O trimestre jan-fev-mar/2026 mostra uma piora pontual e sazonal em relação ao "
            "trimestre imediatamente anterior: menos ocupados (-153.000), mais desocupados "
            "(+86.000), mais desalentados e taxa de desocupação 2,3 p.p. maior. Na comparação "
            "com o mesmo período de 2025, porém, o quadro é de melhora estrutural: a desocupação "
            "está estável no menor patamar para um 1º trimestre desde 2012, o emprego com "
            "carteira no setor privado cresceu 10,2%, o setor público expandiu 14,3%, o "
            "rendimento real subiu 11,4% e todos os indicadores de subutilização caíram de forma "
            "significativa. Os pontos de atenção são a informalidade em queda concentrada em "
            "segmentos frágeis (trabalho doméstico, empregadores sem CNPJ) e a perda persistente "
            "de postos na agropecuária e na indústria.",
            size="sm",
        ),
    ],
)

explorer = dmc.Stack(
    gap="md",
    children=[
        section_title("7", "Explorar os dados"),
        dmc.Card(
            withBorder=True, radius="md", padding="lg",
            children=[
                dmc.Grid(
                    gutter="md",
                    children=[
                        dmc.GridCol(
                            dmc.Select(
                                id="filter-section",
                                label="Área de análise",
                                data=["Todas"] + df["secao"].drop_duplicates().tolist(),
                                value="Todas",
                                clearable=False,
                            ),
                            span={"base": 12, "md": 3},
                        ),
                        dmc.GridCol(
                            dmc.MultiSelect(
                                id="filter-periods",
                                label="Períodos",
                                data=PERIOD_ORDER,
                                value=PERIOD_ORDER,
                            ),
                            span={"base": 12, "md": 5},
                        ),
                        dmc.GridCol(
                            dmc.Group(
                                dmc.Button("Baixar CSV filtrado", id="download-button",
                                           variant="filled", color="blue"),
                                justify="flex-end", align="flex-end", h="100%",
                            ),
                            span={"base": 12, "md": 4},
                        ),
                    ],
                ),
                dcc.Download(id="download-data"),
                dag.AgGrid(
                    id="data-grid",
                    className="ag-theme-alpine",
                    columnDefs=[
                        {"field": "secao", "headerName": "Seção", "width": 150},
                        {"field": "grupo", "headerName": "Grupo", "width": 170},
                        {"field": "indicador", "headerName": "Indicador", "flex": 1, "minWidth": 260},
                        {"field": "unidade", "headerName": "Unidade", "width": 110},
                        {"field": "periodo", "headerName": "Período", "width": 140},
                        {"field": "valor", "headerName": "Valor", "width": 110, "type": "numericColumn"},
                        {"field": "var_trimestral", "headerName": "Var. trim.", "width": 120},
                        {"field": "sig_trimestral", "headerName": "Situação trim.", "width": 130},
                        {"field": "var_anual", "headerName": "Var. anual", "width": 120},
                        {"field": "sig_anual", "headerName": "Situação anual", "width": 130},
                    ],
                    defaultColDef={"sortable": True, "filter": True, "resizable": True},
                    dashGridOptions={
                        "pagination": True,
                        "paginationPageSize": 14,
                        "domLayout": "autoHeight",
                    },
                    style={"marginTop": 16},
                ),
            ],
        ),
    ],
)

ceara_analysis = dmc.Stack(
    gap="md",
    children=[
        how_to_read,
        kpis,
        dmc.Stack(
            gap="md",
            children=[
                section_title("0", "Evolução recente — atual vs. 3 trimestres anteriores"),
                narrative(
                    dmc.Text(
                        f"Série montada a partir dos PDFs em pnad/. "
                        f"Períodos: {' → '.join(PERIOD_ORDER)}.",
                        size="sm",
                    )
                ),
                dmc.SimpleGrid(
                    cols={"base": 1, "lg": 2},
                    spacing="md",
                    children=[
                        dmc.Card(
                            withBorder=True, radius="md", padding="md",
                            children=[
                                series_line_chart(
                                    [
                                        "Taxa de desocupação",
                                        "Nível da ocupação",
                                        "Taxa de participação na força de trabalho",
                                    ],
                                    "Taxas do mercado de trabalho (%)",
                                    "%",
                                )
                            ],
                        ),
                        dmc.Card(
                            withBorder=True, radius="md", padding="md",
                            children=[
                                series_line_chart(
                                    ["Ocupadas", "Desocupadas"],
                                    "Ocupadas e desocupadas (pessoas)",
                                    "Mil pessoas",
                                )
                            ],
                        ),
                        dmc.Card(
                            withBorder=True, radius="md", padding="md",
                            children=[
                                series_line_chart(
                                    ["Rendimento médio mensal real habitual"],
                                    "Rendimento médio real habitual (R$)",
                                    "R$",
                                )
                            ],
                        ),
                        dmc.Card(
                            withBorder=True, radius="md", padding="md",
                            children=[
                                series_line_chart(
                                    ["Taxa composta de subutilização da força de trabalho"],
                                    "Subutilização composta (%)",
                                    "%",
                                )
                            ],
                        ),
                    ],
                ),
            ],
        ),
        section1,
        section2,
        section3,
        section4,
        section5,
        section6,
        reading,
        explorer,
    ],
)

def compare_grid_records() -> list[dict]:
    table = df_cmp.copy()
    table["valor"] = [
        compare_value_label(float(value), unit)
        for value, unit in zip(table["valor"], table["unidade"], strict=True)
    ]
    table["unidade"] = table["unidade"].replace(
        {"Mil pessoas": "pessoas", "R$ milhões": "R$"}
    )
    geo_rank = {geo: index for index, geo in enumerate(GEO_ORDER)}
    table["ordem"] = table["geografia"].map(geo_rank)
    table = table.sort_values(["ordem", "indicador"])
    return table[
        ["geografia", "grupo_geografico", "indicador", "unidade", "valor"]
    ].to_dict("records")


def glossary_item(title: str, plain: str, detail: str) -> dmc.Stack:
    return dmc.Stack(
        gap=4,
        children=[
            dmc.Text(title, fw=700, size="sm"),
            dmc.Text(plain, size="sm"),
            dmc.Text(detail, size="xs", c="dimmed"),
        ],
    )


GLOSSARY_ITEMS = [
    (
        "Taxa de desocupação",
        "É o percentual de pessoas que estão sem trabalho e procurando emprego.",
        "Em linguagem simples: a cada 100 pessoas na força de trabalho, quantas estão desempregadas. "
        "Quanto menor, melhor.",
    ),
    (
        "Nível da ocupação",
        "É o percentual de pessoas de 14 anos ou mais que estão trabalhando.",
        "Mostra quanto da população em idade de trabalhar está ocupada. "
        "Quanto maior, melhor.",
    ),
    (
        "Taxa de participação na força de trabalho",
        "É o percentual de pessoas que estão no mercado de trabalho — trabalhando ou procurando emprego.",
        "Ajuda a entender se mais gente está entrando ou saindo do mercado. "
        "Não mede desemprego sozinha.",
    ),
    (
        "Ocupadas",
        "É a quantidade de pessoas que estão trabalhando.",
        "Inclui emprego formal, informal, conta própria e outras formas de ocupação. "
        "Aqui o número aparece em pessoas (não em milhares).",
    ),
    (
        "Desocupadas",
        "É a quantidade de pessoas sem trabalho que estão buscando uma ocupação.",
        "São os desempregados na definição da PNAD. Quem desistiu de procurar não entra aqui.",
    ),
    (
        "Rendimento médio mensal real habitual",
        "É quanto, em média, a pessoa ocupada costuma ganhar por mês, já descontando a inflação.",
        "“Real” significa que o valor foi ajustado para permitir comparação no tempo. "
        "“Habitual” é o rendimento normalmente recebido, não um mês atípico.",
    ),
    (
        "Taxa composta de subutilização da força de trabalho",
        "É um indicador mais amplo do que o desemprego: junta quem está desempregado, "
        "quem trabalha menos horas do que gostaria e quem poderia trabalhar, mas não está plenamente disponível.",
        "Serve para ver a folga do mercado de trabalho além da taxa de desocupação. "
        "Quanto menor, melhor.",
    ),
]


glossary_block = dmc.Card(
    withBorder=True,
    radius="md",
    padding="xl",
    children=[
        dmc.Title("O que significa cada indicador?", order=3, mb="xs"),
        dmc.Text(
            "Guia rápido, em linguagem simples, para interpretar os números do painel.",
            size="sm",
            c="dimmed",
            mb="md",
        ),
        dmc.SimpleGrid(
            cols={"base": 1, "md": 2},
            spacing="lg",
            children=[
                glossary_item(title, plain, detail)
                for title, plain, detail in GLOSSARY_ITEMS
            ],
        ),
    ],
)


comparison_tab = dmc.Stack(
    gap="md",
    mt="md",
    children=[
        dmc.Card(
            withBorder=True,
            radius="md",
            padding="lg",
            children=[
                dmc.Title("Comparativo regional", order=3, mb="xs"),
                dmc.Text(
                    "Principais indicadores do Ceará frente ao Brasil (agregado das cinco "
                    "macrorregiões do quadro sintético), ao Nordeste e aos demais estados "
                    "da região — trimestre jan-fev-mar/2026.",
                    size="sm",
                    c="dimmed",
                ),
            ],
        ),
        dmc.SimpleGrid(
            cols={"base": 1, "sm": 2, "lg": 4},
            spacing="md",
            children=[
                compare_summary_card("Taxa de desocupação", "Taxa de desocupação"),
                compare_summary_card("Nível da ocupação", "Nível da ocupação"),
                compare_summary_card("Ocupadas", "Ocupadas"),
                compare_summary_card("Rendimento médio real", "Rendimento médio mensal real habitual"),
            ],
        ),
        dmc.Card(
            withBorder=True,
            radius="md",
            padding="lg",
            children=[
                dmc.Select(
                    id="compare-indicator",
                    label="Indicador para comparar",
                    data=[{"label": item, "value": item} for item in COMPARE_INDICATORS],
                    value="Taxa de desocupação",
                    clearable=False,
                    mb="md",
                ),
                dcc.Store(id="compare-hidden-geos", data=[]),
                html.Div(id="compare-chart-container"),
            ],
        ),
        dmc.Card(
            withBorder=True,
            radius="md",
            padding="lg",
            children=[
                dmc.Text("Tabela comparativa completa", fw=600, mb="sm"),
                dag.AgGrid(
                    id="compare-grid",
                    className="ag-theme-alpine",
                    rowData=compare_grid_records(),
                    columnDefs=[
                        {"field": "geografia", "headerName": "Geografia", "width": 170},
                        {"field": "grupo_geografico", "headerName": "Grupo", "width": 150},
                        {"field": "indicador", "headerName": "Indicador", "flex": 1, "minWidth": 260},
                        {"field": "unidade", "headerName": "Unidade", "width": 110},
                        {"field": "valor", "headerName": "Valor", "width": 140},
                    ],
                    defaultColDef={"sortable": True, "filter": True, "resizable": True},
                    dashGridOptions={
                        "pagination": True,
                        "paginationPageSize": 12,
                        "domLayout": "autoHeight",
                    },
                ),
            ],
        ),
        glossary_block,
    ],
)

footer = dmc.Text(
    "Nota metodológica: variações de taxas em pontos percentuais (p.p.); demais variações em "
    "valores absolutos e percentuais. As situações (setas) reproduzem os testes de significância "
    "estatística do IBGE — diferenças classificadas como estáveis não passam no teste, ainda que "
    "os números pareçam variar. Estimativas populacionais são exibidas em número absoluto de "
    "pessoas (a fonte IBGE publica em milhares). Fonte: IBGE, PNAD Contínua Trimestral, "
    "divulgação de maio de 2026.",
    size="xs",
    c="dimmed",
    mt="xl",
    mb="xl",
)

_update_children: list = [
    dmc.Paper(
        withBorder=True,
        radius="md",
        p="lg",
        children=[
            dmc.Text("Atualizar dados por upload de PDF", fw=700, size="lg"),
            dmc.Text(
                "Envie o quadro sintético do IBGE no padrão "
                "pnadc_YYYYQQ_trimestre_quadroSintetico.pdf. "
                "O sistema regenera a série temporal e o comparativo regional, "
                "e pode publicar os arquivos no GitHub para o Railway redesplegar.",
                size="sm",
                c="dimmed",
                mt="xs",
            ),
            dmc.Alert(
                "A aba Análise do Ceará (detalhe com setas de significância) "
                "usa uma base curada e não é reescrita automaticamente neste fluxo.",
                color="yellow",
                variant="light",
                mt="md",
                title="Limitação",
            ),
        ],
    ),
]
if not data_update.upload_enabled():
    _update_children.append(
        dmc.Alert(
            "Defina ADMIN_UPLOAD_TOKEN no ambiente para autorizar uploads. "
            "Para publicar no GitHub, configure também GITHUB_TOKEN e GITHUB_REPO.",
            color="orange",
            variant="light",
            title="Upload ainda não configurado",
        )
    )
_update_children.append(
    dmc.Card(
        withBorder=True,
        radius="md",
        padding="lg",
        children=[
            dmc.PasswordInput(
                id="upload-admin-token",
                label="Token de administração",
                description="Mesmo valor da variável ADMIN_UPLOAD_TOKEN",
                placeholder="••••••••",
                mb="md",
            ),
            dcc.Upload(
                id="pdf-upload",
                accept=".pdf,application/pdf",
                max_size=80 * 1024 * 1024,
                children=html.Div(
                    [
                        dmc.Text("Arraste o PDF aqui ou clique para selecionar", fw=600),
                        dmc.Text(
                            "Somente quadro sintético IBGE (.pdf)",
                            size="xs",
                            c="dimmed",
                        ),
                    ],
                    style={"padding": "28px 16px", "textAlign": "center"},
                ),
                style={
                    "borderWidth": "1px",
                    "borderStyle": "dashed",
                    "borderRadius": "10px",
                    "borderColor": "#C5CDD6",
                    "background": "#F8FAFC",
                    "cursor": "pointer",
                    "marginBottom": "12px",
                },
            ),
            dmc.Text(id="pdf-upload-filename", size="sm", c="dimmed", mb="md"),
            dmc.Checkbox(
                id="upload-push-github",
                label="Enviar CSV (e PDF) automaticamente para o GitHub",
                checked=data_update.github_configured(),
                disabled=not data_update.github_configured(),
                mb="md",
            ),
            dmc.Text(
                "Para publicar no GitHub, defina GITHUB_TOKEN no Railway "
                f"(repositório: {data_update.DEFAULT_GITHUB_REPO})."
                if not data_update.github_configured()
                else f"GitHub pronto — envio para {data_update.github_repo()}.",
                size="xs",
                c="dimmed",
                mb="md",
            ),
            dmc.Group(
                [
                    dmc.Button(
                        "Processar upload",
                        id="upload-process-btn",
                        color="blue",
                        disabled=not data_update.upload_enabled(),
                    ),
                ],
                align="center",
            ),
            dcc.Loading(
                html.Div(id="upload-result", style={"marginTop": "16px"}),
                type="default",
            ),
        ],
    )
)
update_tab = dmc.Stack(gap="md", children=_update_children)

app.layout = dmc.MantineProvider(
    theme={"fontFamily": "Inter, Segoe UI, sans-serif", "primaryColor": "blue"},
    children=[
        header,
        dmc.Container(
            size="xl",
            children=[
                dmc.Tabs(
                    value="ceara",
                    children=[
                        dmc.TabsList(
                            [
                                dmc.TabsTab("Análise do Ceará", value="ceara"),
                                dmc.TabsTab("Comparativo regional", value="comparativo"),
                                dmc.TabsTab("Atualizar dados", value="atualizar"),
                            ],
                            mb="md",
                        ),
                        dmc.TabsPanel(ceara_analysis, value="ceara"),
                        dmc.TabsPanel(comparison_tab, value="comparativo"),
                        dmc.TabsPanel(update_tab, value="atualizar"),
                    ],
                ),
                footer,
            ],
        ),
    ],
)


def filtered_frame(section: str, periods: list[str] | None) -> pd.DataFrame:
    subset = df.copy()
    if section and section != "Todas":
        subset = subset[subset["secao"] == section]
    if periods:
        subset = subset[subset["periodo"].isin(periods)]
    return subset.sort_values(["secao", "grupo", "indicador", "ordem_periodo"])


def grid_records(subset: pd.DataFrame) -> list[dict]:
    table = subset.copy()

    def fmt_var(row: pd.Series, scope: str) -> str:
        abs_value = row[f"variacao_{scope}_abs"]
        if pd.isna(abs_value):
            return ""
        if row["unidade"] == "%":
            return f"{'+' if abs_value >= 0 else ''}{br(abs_value)} p.p."
        if row["unidade"] == "Mil pessoas":
            return f"{'+' if abs_value >= 0 else ''}{br(people(abs_value), 0)}"
        if row["unidade"] == "R$ milhões":
            return f"{'+' if abs_value >= 0 else ''}{br(abs_value * 1_000_000, 0)}"
        pct = row[f"variacao_{scope}_pct"]
        return f"{'+' if pct >= 0 else ''}{br(pct)}%"

    def fmt_sig(row: pd.Series, scope: str) -> str:
        situ = row[f"situacao_{scope}"]
        if pd.isna(situ):
            return ""
        return f"{SIG_ARROW[situ]} {SIG_LABEL[situ]}"

    def fmt_unit(unit: str) -> str:
        if unit == "Mil pessoas":
            return "pessoas"
        if unit == "R$ milhões":
            return "R$"
        return unit

    table["var_trimestral"] = table.apply(fmt_var, axis=1, scope="trimestral")
    table["var_anual"] = table.apply(fmt_var, axis=1, scope="anual")
    table["sig_trimestral"] = table.apply(fmt_sig, axis=1, scope="trimestral")
    table["sig_anual"] = table.apply(fmt_sig, axis=1, scope="anual")
    table["valor"] = [
        display_value(float(value), unit)
        for value, unit in zip(table["valor"], table["unidade"], strict=True)
    ]
    table["unidade"] = table["unidade"].map(fmt_unit)
    columns = [
        "secao", "grupo", "indicador", "unidade", "periodo", "valor",
        "var_trimestral", "sig_trimestral", "var_anual", "sig_anual",
    ]
    return table[columns].to_dict("records")


@callback(
    Output("compare-hidden-geos", "data"),
    Input("compare-chart", "clickData"),
    Input("compare-restore-geos", "n_clicks"),
    Input("compare-indicator", "value"),
    State("compare-hidden-geos", "data"),
    prevent_initial_call=True,
)
def update_hidden_compare_geos(click_data, _restore_clicks, _indicator, hidden):
    triggered = ctx.triggered_id
    if triggered in {"compare-indicator", "compare-restore-geos"}:
        return []
    if triggered == "compare-chart" and click_data and click_data.get("points"):
        geo = click_data["points"][0].get("y")
        if not geo:
            return no_update
        current = list(hidden or [])
        if geo in current:
            return [item for item in current if item != geo]
        return current + [geo]
    return no_update


@callback(
    Output("compare-chart-container", "children"),
    Input("compare-indicator", "value"),
    Input("compare-hidden-geos", "data"),
)
def update_compare_chart(indicator: str, hidden_geos: list[str] | None):
    unit = df_cmp.loc[df_cmp["indicador"] == indicator, "unidade"].iloc[0]
    with_total = indicator in {"Ocupadas", "Desocupadas"}
    hidden = list(hidden_geos or [])
    subtitle = (
        "Brasil e Nordeste ficam no topo; demais estados em ordem decrescente. "
        "Ceará destacado em azul escuro. "
        "Clique em uma barra para ocultá-la e comparar menos geografias."
    )
    if with_total:
        subtitle += (
            " Cada barra empilhada mostra a parcela do indicador (tom mais forte) "
            "sobre a quantidade total de pessoas de 14 anos ou mais "
            "(rótulo à direita = total). Na legenda, clique para ligar/desligar camadas."
        )

    controls = []
    if hidden:
        controls.append(
            dmc.Group(
                justify="space-between",
                align="center",
                children=[
                    dmc.Text(
                        f"Ocultos: {', '.join(hidden)}",
                        size="xs",
                        c="dimmed",
                    ),
                    dmc.Button(
                        "Mostrar todos",
                        id="compare-restore-geos",
                        size="xs",
                        variant="light",
                    ),
                ],
            )
        )
    else:
        controls.append(
            html.Div(
                dmc.Button(
                    "Mostrar todos",
                    id="compare-restore-geos",
                    size="xs",
                    variant="light",
                    style={"display": "none"},
                )
            )
        )

    return dmc.Stack(
        gap="xs",
        children=[
            dmc.Text(f"Comparativo — {indicator}", fw=600),
            dmc.Text(subtitle, size="xs", c="dimmed"),
            *controls,
            compare_chart(indicator, hidden),
            dmc.Text(
                f"Unidade de referência: {unit.replace('Mil pessoas', 'pessoas')}",
                size="xs",
                c="dimmed",
            ),
        ],
    )


@callback(
    Output("data-grid", "rowData"),
    Input("filter-section", "value"),
    Input("filter-periods", "value"),
)
def update_grid(section: str, periods: list[str]) -> list[dict]:
    return grid_records(filtered_frame(section, periods))


@callback(
    Output("download-data", "data"),
    Input("download-button", "n_clicks"),
    State("filter-section", "value"),
    State("filter-periods", "value"),
    prevent_initial_call=True,
)
def download_filtered(_clicks: int, section: str, periods: list[str]) -> dict:
    subset = filtered_frame(section, periods)
    return dcc.send_data_frame(
        subset.to_csv, "pnad_ce_filtro.csv", index=False, encoding="utf-8-sig"
    )


@callback(
    Output("pdf-upload-filename", "children"),
    Input("pdf-upload", "filename"),
)
def show_upload_filename(filename: str | None):
    if not filename:
        return "Nenhum arquivo selecionado."
    return f"Arquivo selecionado: {filename}"


@callback(
    Output("upload-result", "children"),
    Input("upload-process-btn", "n_clicks"),
    State("pdf-upload", "contents"),
    State("pdf-upload", "filename"),
    State("upload-admin-token", "value"),
    State("upload-push-github", "checked"),
    prevent_initial_call=True,
)
def process_pdf_upload(n_clicks, contents, filename, token, push_github):
    if not n_clicks:
        return no_update
    if not contents or not filename:
        return dmc.Alert(
            "Selecione um PDF antes de processar.",
            color="red",
            title="Falha",
        )
    try:
        result = data_update.process_upload(
            contents=contents,
            filename=filename,
            token=token,
            push_github=bool(push_github),
        )
        reload_runtime_data()
    except PermissionError as exc:
        return dmc.Alert(str(exc), color="red", title="Não autorizado")
    except Exception as exc:  # noqa: BLE001 - feedback direto na UI
        return dmc.Alert(str(exc), color="red", title="Erro no processamento")

    stats = result["stats"]
    details = [
        dmc.Text(f"PDF: {result['pdf']}", size="sm"),
        dmc.Text(
            "Série: "
            + " | ".join(stats.get("serie_periodos", []))
            + f" ({stats.get('serie_linhas', 0)} linhas)",
            size="sm",
        ),
        dmc.Text(
            f"Comparativo: {stats.get('comparativo_periodo')} "
            f"({stats.get('comparativo_linhas', 0)} linhas) "
            f"via {stats.get('pdf_usado_comparativo')}",
            size="sm",
        ),
        dmc.Text(result["aviso"], size="sm", c="dimmed", mt="xs"),
        dmc.Text(
            "Recarregue a página para ver os gráficos com os novos números.",
            size="sm",
            fw=600,
            mt="xs",
        ),
    ]
    if result.get("github"):
        if result["github"].get("skipped"):
            details.append(
                dmc.Alert(
                    "Os CSVs e o PDF ficaram só no servidor Railway. "
                    "No GitHub (pauloqxm/set-pnad) nada foi alterado porque "
                    "GITHUB_TOKEN não está configurado.",
                    color="orange",
                    title="Não publicado no GitHub",
                    mt="sm",
                )
            )
        else:
            details.append(
                dmc.Text(
                    "Publicado no GitHub ("
                    + result["github"]["repo"]
                    + "@"
                    + result["github"]["branch"]
                    + "): "
                    + ", ".join(result["github"]["arquivos"]),
                    size="xs",
                    c="dimmed",
                    mt="xs",
                )
            )
    title = "Atualização concluída"
    color = "teal"
    if result.get("github", {}).get("skipped"):
        title = "Atualizado no servidor (GitHub pendente)"
        color = "yellow"
    return dmc.Alert(details, color=color, title=title)


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", "8051"))
    debug = os.environ.get("DASH_DEBUG", "0") == "1"
    host = os.environ.get("HOST", "127.0.0.1" if debug else "0.0.0.0")
    app.run(debug=debug, host=host, port=port)
