"""Dashboard analítico da PNAD Contínua no Ceará — 1º trimestre de 2026.

Interface construída com dash-mantine-components (gráficos Recharts) e
dash-ag-grid, organizada como um roteiro de análise: indicadores gerais,
condição de ocupação, posição na ocupação, setores, rendimento,
subutilização e leitura geral, sempre destacando a significância
estatística (setas do IBGE) das variações trimestral e interanual.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback, ctx, dcc, html, no_update
from flask import session

import data_update

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CSV_PATH = DATA_DIR / "pnad_ce_1tri2026.csv"
COMPARE_CSV = DATA_DIR / "pnad_comparativo_1tri2026.csv"
SERIES_CSV = DATA_DIR / "pnad_ce_serie.csv"
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

# Paleta inspirada no painel de referência (navy + teal/seafoam).
THEME = {
    "navy": "#002B49",
    "header": "#002B49",
    "teal_dark": "#1E5A7A",
    "teal": "#72B1A1",
    "green": "#74B484",
    "seafoam": "#99CCAA",
    "bg": "#F5F5F5",
    "card": "#FFFFFF",
    "muted": "#5B6B7A",
    "text": "#1B2433",
}
KPI_CARD_COLORS = (THEME["green"], THEME["teal"], THEME["teal_dark"], THEME["navy"])
CHART_COLORS = [THEME["teal_dark"], THEME["teal"], THEME["green"], "#C47B3A", "#8B5A7A"]


def br(number: float, decimals: int = 1) -> str:
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "@").replace(".", ",").replace("@", ".")


INDICATOR_LABELS = {
    "Rendimento médio mensal real habitual": "Rendimento médio mensal",
}


def indicator_label(name: str) -> str:
    return INDICATOR_LABELS.get(name, name)


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
            return "#A8C5B8"
        if geografia in {"Brasil", "Nordeste"}:
            return "#B7C2CC"
        return "#D6DEE5"
    if geografia == "Ceará":
        return THEME["navy"]
    if geografia in {"Brasil", "Nordeste"}:
        return THEME["teal_dark"]
    return THEME["teal"]


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
                textfont={"size": 10, "family": "Segoe UI, sans-serif", "color": THEME["text"]},
                cliponaxis=False,
                marker={
                    "color": [compare_bar_color(geo, total=True) for geo in geos],
                    "line": {"width": 0},
                    "cornerradius": 6,
                },
                hovertemplate=(
                    "%{y}<br>Demais (até o total 14+): %{customdata[2]}"
                    "<br>Total (14+): %{customdata[1]}"
                    "<br>Participação: %{customdata[0]}"
                    "<br><i>Clique para ocultar</i><extra></extra>"
                ),
                customdata=[
                    [pct, total, br(rem, 0)]
                    for pct, total, rem in zip(
                        percent_labels, total_labels, remainders, strict=True
                    )
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
                textfont={"size": 10, "family": "Segoe UI, sans-serif", "color": THEME["text"]},
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
        tick_text = [f"{br(tick, 0)}%" for tick in tick_values]
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
        autosize=True,
        height=max(320, 48 * len(geos) + (110 if with_total else 80)),
        margin={"l": 110, "r": 120 if with_total else 72, "t": 36, "b": 40},
        xaxis={
            "title": None,
            "tickmode": "array",
            "tickvals": tick_values,
            "ticktext": tick_text,
            "tickfont": {"size": 10},
            "gridcolor": "#E6EBF0",
            "zeroline": False,
            "range": [0, max_value * (1.42 if with_total else 1.22)],
        },
        yaxis={"title": None, "automargin": True, "tickfont": {"size": 11}},
        font={"family": "Segoe UI, Candara, sans-serif", "color": THEME["text"], "size": 11},
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=with_total,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 11},
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
        config={"displayModeBar": False, "responsive": True},
        className="chart-responsive",
        style={"width": "100%", "minWidth": 0},
    )


def compare_summary_card(
    title: str,
    indicator: str,
    *,
    color: str = THEME["teal_dark"],
) -> dmc.Card:
    rows = {
        geo: df_cmp[(df_cmp["geografia"] == geo) & (df_cmp["indicador"] == indicator)].iloc[0]
        for geo in ("Ceará", "Brasil", "Nordeste")
    }
    unit = str(rows["Ceará"]["unidade"])
    return dmc.Card(
        className="kpi-card kpi-card--solid",
        withBorder=False,
        radius="md",
        padding="lg",
        style={"background": color, "color": "white", "minHeight": 148},
        children=[
            dmc.Text(
                title,
                size="xs",
                fw=800,
                tt="uppercase",
                style={"letterSpacing": "0.06em", "color": "rgba(255,255,255,0.9)"},
            ),
            dmc.Group(
                justify="space-between",
                mt="md",
                align="flex-start",
                wrap="nowrap",
                children=[
                    dmc.Stack(
                        gap=2,
                        children=[
                            dmc.Text(
                                "Ceará",
                                size="xs",
                                fw=700,
                                style={"color": "rgba(255,255,255,0.78)"},
                            ),
                            dmc.Text(
                                compare_value_label(rows["Ceará"]["valor"], unit),
                                fw=800,
                                className="kpi-value",
                                style={"color": "white", "fontSize": "1.35rem", "lineHeight": 1.1},
                            ),
                        ],
                    ),
                    dmc.Stack(
                        gap=2,
                        children=[
                            dmc.Text(
                                "Brasil",
                                size="xs",
                                style={"color": "rgba(255,255,255,0.72)"},
                            ),
                            dmc.Text(
                                compare_value_label(rows["Brasil"]["valor"], unit),
                                size="sm",
                                fw=700,
                                style={"color": "rgba(255,255,255,0.95)"},
                            ),
                        ],
                    ),
                    dmc.Stack(
                        gap=2,
                        children=[
                            dmc.Text(
                                "Nordeste",
                                size="xs",
                                style={"color": "rgba(255,255,255,0.72)"},
                            ),
                            dmc.Text(
                                compare_value_label(rows["Nordeste"]["valor"], unit),
                                size="sm",
                                fw=700,
                                style={"color": "rgba(255,255,255,0.95)"},
                            ),
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


def kpi_card(
    indicator: str,
    section: str,
    description: str,
    *,
    color: str = THEME["teal_dark"],
    title: str | None = None,
) -> dmc.Card:
    row = latest_row(indicator, section)
    current_period = str(row["periodo"])
    prev_period = year_ago_period(current_period)
    prev_row = period_row(indicator, section, prev_period) if prev_period else None
    display_title = title or indicator_label(indicator)

    children = [
        dmc.Text(
            display_title,
            size="xs",
            fw=800,
            tt="uppercase",
            style={"letterSpacing": "0.06em", "color": "rgba(255,255,255,0.9)"},
        ),
        dmc.Text(
            value_text(row),
            fw=800,
            my=10,
            className="kpi-value",
            style={
                "fontSize": "2rem",
                "lineHeight": 1.05,
                "color": "white",
                "letterSpacing": "-0.02em",
            },
        ),
        dmc.Text(description, size="xs", style={"color": "rgba(255,255,255,0.82)"}),
        dmc.Group(
            [sig_badge(row, "trimestral", "no tri.")],
            gap="xs",
            mt="sm",
        ),
    ]

    if prev_row is not None:
        children.append(
            html.Div(
                className="kpi-yoy-box",
                children=[
                    dmc.Text(
                        "Ano anterior",
                        size="xs",
                        fw=700,
                        tt="uppercase",
                        style={
                            "letterSpacing": "0.05em",
                            "color": "rgba(255,255,255,0.72)",
                        },
                    ),
                    dmc.Text(
                        f"{value_text(prev_row)} · {short_tri_label(prev_period)}",
                        size="sm",
                        fw=700,
                        mt=4,
                        style={"color": "rgba(255,255,255,0.98)"},
                    ),
                    dmc.Group(
                        [sig_badge(row, "anual", "no ano")],
                        gap="xs",
                        mt=8,
                    ),
                ],
            )
        )
    else:
        children.append(
            dmc.Group(
                [sig_badge(row, "anual", "no ano")],
                gap="xs",
                mt="sm",
            )
        )

    return dmc.Card(
        className="kpi-card kpi-card--solid",
        withBorder=False,
        radius="md",
        padding="lg",
        style={"background": color, "color": "white", "minHeight": 188},
        children=children,
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
    colors = CHART_COLORS
    # Alterna posição para reduzir sobreposição quando séries ficam próximas.
    text_positions = ("top center", "bottom center", "middle right", "top left")

    for index, indicator in enumerate(indicators):
        rows = df_serie[df_serie["indicador"] == indicator].sort_values("ordem_periodo")
        if rows.empty:
            continue
        values = [float(v) * scale for v in rows["valor"]]
        periods = rows["periodo"].tolist()
        short_x = [short_tri_label(str(period)) for period in periods]
        if unit == "%":
            labels = [f"{br(v)}%" for v in rows["valor"]]
        elif unit == "R$":
            labels = [f"R$ {br(v, 0)}" for v in rows["valor"]]
        elif unit == "R$ milhões":
            labels = [f"R$ {br(v * 1_000_000, 0)}" for v in rows["valor"]]
        else:
            labels = [br(v * scale, 0) for v in rows["valor"]]

        color = colors[index % len(colors)]
        figure.add_trace(
            go.Scatter(
                x=short_x,
                y=values,
                customdata=periods,
                mode="lines+markers+text",
                name=indicator_label(indicator),
                text=labels,
                textposition=text_positions[index % len(text_positions)],
                textfont={"size": 10, "color": color, "family": "Segoe UI, sans-serif"},
                cliponaxis=False,
                line={"width": 2.5, "color": color},
                marker={"size": 7, "color": color},
                hovertemplate="%{customdata}<br>%{text}<extra>"
                + indicator_label(indicator)
                + "</extra>",
            )
        )

    y_values = [v for trace in figure.data for v in (trace.y or [])]
    y_pad = 0.0
    if y_values:
        y_min, y_max = min(y_values), max(y_values)
        span = max(y_max - y_min, abs(y_max) * 0.08, 1.0)
        y_pad = span * 0.18

    figure.update_layout(
        title={"text": title, "x": 0, "font": {"size": 14, "color": THEME["navy"]}},
        template="plotly_white",
        autosize=True,
        height=380,
        margin={"l": 44, "r": 18, "t": 56, "b": 88},
        legend={
            "orientation": "h",
            "y": -0.28,
            "x": 0,
            "font": {"size": 11},
            "bgcolor": "rgba(255,255,255,0.85)",
        },
        xaxis={
            "title": None,
            "type": "category",
            "tickfont": {"size": 11},
            "tickangle": -20,
        },
        yaxis={
            "title": None,
            "gridcolor": "#E6EBF0",
            "zeroline": False,
            "tickfont": {"size": 11},
            "range": (
                [min(y_values) - y_pad, max(y_values) + y_pad] if y_values else None
            ),
        },
        font={"family": "Segoe UI, Candara, sans-serif", "color": THEME["text"], "size": 11},
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
    )
    return dcc.Graph(
        figure=figure,
        config={"displayModeBar": False, "responsive": True},
        className="chart-responsive",
        style={"width": "100%", "minWidth": 0},
    )


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


def _mantine_value_formatter(unit: str) -> dict:
    if unit == "%":
        return {"function": "formatPercentPtBR"}
    if unit in {"R$", "R$ milhões"}:
        return {"function": "formatCurrencyPtBR"}
    return {"function": "formatNumberPtBR"}


def _chart_value_formatter(unit: str, scale: float = 1.0) -> dict:
    if unit == "Mil pessoas" and scale != 1:
        return {"function": "formatNumberPtBR"}
    if unit == "R$ milhões" and scale != 1:
        return {"function": "formatCurrencyPtBR"}
    return _mantine_value_formatter(unit)


def line_chart(
    indicators: list[str],
    section: str,
    unit: str,
    height: int = 300,
    scale: float = 1.0,
) -> dmc.LineChart | dcc.Graph:
    display_unit = unit if scale == 1 else ("pessoas" if unit == "Mil pessoas" else unit)
    if all(indicator in set(df_serie["indicador"]) for indicator in indicators):
        return series_line_chart(
            indicators,
            title=f"{' · '.join(indicators[:2])}{'…' if len(indicators) > 2 else ''}",
            unit=display_unit if scale != 1 or unit != "Mil pessoas" else unit,
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
        unit="" if scale != 1 and unit == "Mil pessoas" else ("" if unit in {"R$", "R$ milhões"} else unit),
        withDots=True,
        strokeWidth=2.5,
        gridAxis="xy",
        withXAxis=True,
        withYAxis=True,
        yAxisProps={"domain": ["auto", "auto"], "width": 96},
        valueFormatter=_chart_value_formatter(unit, scale),
    )


def grouped_bar_chart(
    indicators: list[str],
    section: str,
    unit: str,
    height: int = 320,
    scale: float = 1.0,
) -> dmc.BarChart:
    data = quarters_chart_data(indicators, section, scale=scale)
    # Eixo X abreviado no padrão brasileiro de trimestre.
    for entry in data:
        entry["periodo"] = short_tri_label(str(entry["periodo"]))
    return dmc.BarChart(
        h=height,
        data=data,
        dataKey="periodo",
        series=[
            {"name": name, "color": PALETTE[i % len(PALETTE)]}
            for i, name in enumerate(indicators)
        ],
        withLegend=True,
        legendProps={"verticalAlign": "bottom"},
        unit="" if scale != 1 and unit == "Mil pessoas" else ("" if unit in {"R$", "R$ milhões"} else unit),
        gridAxis="y",
        yAxisProps={"width": 96},
        valueFormatter=_chart_value_formatter(unit, scale),
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
        valueFormatter={"function": "formatPercentPtBR"},
    )


def narrative(children) -> dmc.Alert:
    return dmc.Alert(children, color="cyan", variant="light", radius="md", className="panel-narrative")


def load_narratives_payload() -> dict:
    path = DATA_DIR / "narratives.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    try:
        import generate_narratives

        return generate_narratives.load_narratives()
    except Exception:  # noqa: BLE001
        return {}


def bootstrap_narratives() -> dict:
    """Se houver chave de IA e o JSON ainda for template, regenera no boot."""
    try:
        import generate_narratives

        return generate_narratives.ensure_ai_narratives()
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: não foi possível regenerar narrativas com IA ({exc})")
        return load_narratives_payload()


NARRATIVES_PAYLOAD = bootstrap_narratives()
SECTION_NARRATIVES = {
    str(key): str(value)
    for key, value in (NARRATIVES_PAYLOAD.get("sections") or {}).items()
}
NARRATIVES_FROM_AI = str(NARRATIVES_PAYLOAD.get("source", "")).lower() in {
    "groq",
    "gemini",
}


def ai_assist_badge() -> dmc.Tooltip:
    return dmc.Tooltip(
        label="Texto feito com auxílio de IA",
        withArrow=True,
        position="left",
        children=html.Span(
            "✦ IA",
            className="ai-assist-badge",
            role="img",
            **{"aria-label": "Texto feito com auxílio de IA"},
        ),
    )


def narrative_md(section_key: str, fallback: str) -> dmc.Alert:
    text = SECTION_NARRATIVES.get(section_key) or fallback
    body = dcc.Markdown(
        text,
        className="narrative-md",
        dangerously_allow_html=False,
    )
    if not NARRATIVES_FROM_AI:
        return narrative(body)
    return narrative(
        dmc.Group(
            align="flex-start",
            justify="space-between",
            gap="sm",
            wrap="nowrap",
            children=[
                html.Div(body, style={"flex": "1 1 auto", "minWidth": 0}),
                ai_assist_badge(),
            ],
        )
    )


def section_title(number: str, text: str) -> dmc.Group:
    return dmc.Group(
        [
            dmc.Badge(
                number,
                size="lg",
                radius="sm",
                variant="filled",
                style={"background": THEME["seafoam"], "color": THEME["navy"]},
            ),
            dmc.Title(text, order=3, style={"color": THEME["navy"]}),
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


def auth_credentials() -> tuple[str, str]:
    """Credenciais do painel: USUARIO/SENHA (aliases AUTH_USERNAME/AUTH_PASSWORD)."""
    username = (
        os.environ.get("USUARIO", "").strip()
        or os.environ.get("AUTH_USERNAME", "").strip()
    )
    password = (
        os.environ.get("SENHA", "").strip()
        or os.environ.get("AUTH_PASSWORD", "").strip()
    )
    return username, password


def auth_configured() -> bool:
    username, password = auth_credentials()
    return bool(username and password)


def is_logged_in() -> bool:
    return bool(session.get("authenticated"))


_username, _password = auth_credentials()
_server_secret = os.environ.get("SECRET_KEY", "").strip()
if not _server_secret:
    if _username and _password:
        _server_secret = hashlib.sha256(
            f"{_username}:{_password}:pnad-ceara".encode("utf-8")
        ).hexdigest()
    else:
        _server_secret = secrets.token_hex(32)
server.secret_key = _server_secret
server.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

_desoc = latest_row("Taxa de desocupação", "Mercado de trabalho")
_ocup = latest_row("Ocupadas", "Mercado de trabalho")
_rend = latest_row("Rendimento médio mensal real habitual", "Rendimento")

header = dmc.Paper(
    className="app-header",
    radius=0,
    p="xl",
    style={"backgroundColor": THEME["header"], "color": "white"},
    children=dmc.Container(
        size="xl",
        px={"base": "sm", "sm": "md", "lg": "xl"},
        children=dmc.Group(
            justify="space-between",
            align="center",
            wrap="wrap",
            gap="lg",
            children=[
                dmc.Stack(
                    gap=4,
                    className="header-title-block",
                    children=[
                        dmc.Text(
                            "SECRETARIA DO TRABALHO DO CEARÁ",
                            size="xs",
                            fw=800,
                            style={"letterSpacing": "0.1em", "color": THEME["seafoam"]},
                        ),
                        dmc.Title(
                            "PNAD Contínua — Ceará",
                            order=1,
                            className="header-title",
                            style={"color": "white", "margin": 0},
                        ),
                        dmc.Text(
                            f"Trimestre atual: {LATEST}",
                            className="header-subtitle",
                            style={"color": "rgba(255,255,255,0.78)"},
                        ),
                    ],
                ),
                dmc.Group(
                    gap="xl",
                    align="center",
                    wrap="wrap",
                    className="header-metrics",
                    children=[
                        dmc.Stack(
                            gap=0,
                            align="flex-end",
                            className="header-metric",
                            children=[
                                dmc.Text(
                                    value_text(_desoc),
                                    fw=800,
                                    className="header-metric-value",
                                    style={"color": "white", "lineHeight": 1},
                                ),
                                dmc.Text(
                                    "TAXA DE DESOCUPAÇÃO",
                                    size="xs",
                                    fw=700,
                                    className="header-metric-label",
                                    style={"color": THEME["seafoam"], "letterSpacing": "0.04em"},
                                ),
                            ],
                        ),
                        dmc.Stack(
                            gap=0,
                            align="flex-end",
                            className="header-metric",
                            children=[
                                dmc.Text(
                                    value_text(_ocup),
                                    fw=800,
                                    className="header-metric-value",
                                    style={"color": "white", "lineHeight": 1},
                                ),
                                dmc.Text(
                                    "OCUPADAS",
                                    size="xs",
                                    fw=700,
                                    className="header-metric-label",
                                    style={"color": THEME["seafoam"], "letterSpacing": "0.04em"},
                                ),
                            ],
                        ),
                        dmc.Stack(
                            gap=0,
                            align="flex-end",
                            className="header-metric",
                            children=[
                                dmc.Text(
                                    value_text(_rend),
                                    fw=800,
                                    className="header-metric-value",
                                    style={"color": "white", "lineHeight": 1},
                                ),
                                dmc.Text(
                                    "RENDIMENTO MÉDIO",
                                    size="xs",
                                    fw=700,
                                    className="header-metric-label",
                                    style={"color": THEME["seafoam"], "letterSpacing": "0.04em"},
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    ),
)

how_to_read = dmc.Card(
    className="panel-card",
    withBorder=True,
    radius="md",
    padding="lg",
    mt="xl",
    children=[
        dmc.Title("Como ler os dados", order=4, mb="xs", style={"color": THEME["navy"]}),
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
        kpi_card(
            "Taxa de desocupação",
            "Mercado de trabalho",
            "Percentual de desocupados na força de trabalho",
            color=KPI_CARD_COLORS[0],
        ),
        kpi_card(
            "Ocupadas",
            "Mercado de trabalho",
            "Pessoas de 14 anos ou mais trabalhando",
            color=KPI_CARD_COLORS[1],
        ),
        kpi_card(
            "Desocupadas",
            "Mercado de trabalho",
            "Pessoas em busca de trabalho",
            color=KPI_CARD_COLORS[2],
        ),
        kpi_card(
            "Rendimento médio mensal real habitual",
            "Rendimento",
            "Todos os trabalhos, valores reais",
            color=KPI_CARD_COLORS[3],
            title="Rendimento médio mensal",
        ),
    ],
)

section1 = dmc.Stack(
    gap="md",
    children=[
        section_title("1", "Indicadores gerais do mercado de trabalho"),
        narrative_md(
            "mercado",
            "A taxa de desocupação, o nível da ocupação e a participação na força de "
            "trabalho do Ceará são atualizados a partir da base detalhada da PNAD Contínua.",
        ),
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
        narrative_md(
            "populacao",
            "Os estoques de ocupados, desocupados e pessoas fora da força de trabalho "
            "são atualizados automaticamente a cada nova base.",
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
        narrative_md(
            "ocupacao",
            "A composição da ocupação por posição e categoria é atualizada com base "
            "nas variações trimestral e anual da PNAD Contínua.",
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
        narrative_md(
            "atividades",
            "Os movimentos setoriais da ocupação são atualizados automaticamente a "
            "partir das variações significativas da base detalhada.",
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
        narrative_md(
            "rendimento",
            "O rendimento médio mensal e a massa de rendimento são atualizados "
            "automaticamente com a base da PNAD Contínua.",
        ),
        dmc.SimpleGrid(
            cols={"base": 1, "md": 2},
            spacing="md",
            children=[
                dmc.Card(
                    withBorder=True, radius="md", padding="lg",
                    children=[
                        dmc.Text("Rendimento médio mensal (R$)", fw=600, mb="sm"),
                        grouped_bar_chart(
                            ["Rendimento médio mensal real habitual"], "Rendimento", "R$", 280,
                        ),
                    ],
                ),
                dmc.Card(
                    withBorder=True, radius="md", padding="lg",
                    children=[
                        dmc.Text("Massa de rendimento (R$)", fw=600, mb="sm"),
                        grouped_bar_chart(
                            ["Massa de rendimento mensal real habitual"],
                            "Rendimento", "R$ milhões", 280, scale=1_000_000,
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
        narrative_md(
            "subutilizacao",
            "Os indicadores ampliados de subutilização são atualizados "
            "automaticamente com a base detalhada da PNAD Contínua.",
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
                        {"field": "valor", "headerName": "Valor", "width": 140},
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
                                    "Rendimento médio mensal (R$)",
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
    table["indicador"] = table["indicador"].map(indicator_label)
    table["unidade"] = table["unidade"].replace(
        {"Mil pessoas": "pessoas", "R$ milhões": "R$"}
    )
    geo_rank = {geo: index for index, geo in enumerate(GEO_ORDER)}
    table["ordem"] = table["geografia"].map(geo_rank)
    table = table.sort_values(["ordem", "indicador"])
    return table[
        ["geografia", "grupo_geografico", "indicador", "unidade", "valor"]
    ].to_dict("records")


def bootstrap_glossary() -> dict:
    try:
        import generate_narratives

        return generate_narratives.ensure_ai_glossary()
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: glossário IA indisponível ({exc})")
        path = DATA_DIR / "glossary.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"source": "template", "items": []}


GLOSSARY_PAYLOAD = bootstrap_glossary()
GLOSSARY_FROM_AI = str(GLOSSARY_PAYLOAD.get("source", "")).lower() in {
    "groq",
    "gemini",
}
GLOSSARY_ITEMS = list(GLOSSARY_PAYLOAD.get("items") or [])
if not GLOSSARY_ITEMS:
    # Fallback estático se o JSON ainda não existir.
    GLOSSARY_ITEMS = [
        {
            "id": "desocupacao",
            "question": "O que é a taxa de desocupação?",
            "answer": (
                "É o percentual de pessoas que estão sem trabalho e procurando emprego. "
                "Quanto menor, melhor."
            ),
        },
        {
            "id": "nivel_ocupacao",
            "question": "O que é o nível da ocupação?",
            "answer": (
                "É o percentual de pessoas de 14 anos ou mais que estão trabalhando. "
                "Quanto maior, melhor."
            ),
        },
        {
            "id": "participacao",
            "question": "O que é a taxa de participação na força de trabalho?",
            "answer": (
                "É o percentual de pessoas que estão no mercado de trabalho — trabalhando "
                "ou procurando emprego."
            ),
        },
        {
            "id": "ocupadas",
            "question": "O que significa o número de pessoas ocupadas?",
            "answer": "É a quantidade de pessoas que estão trabalhando.",
        },
        {
            "id": "desocupadas",
            "question": "O que significa o número de pessoas desocupadas?",
            "answer": (
                "É a quantidade de pessoas sem trabalho que estão buscando uma ocupação."
            ),
        },
        {
            "id": "rendimento",
            "question": "O que é o rendimento médio mensal?",
            "answer": (
                "É quanto, em média, a pessoa ocupada costuma ganhar por mês, "
                "já descontando a inflação."
            ),
        },
        {
            "id": "subutilizacao",
            "question": "O que é a taxa composta de subutilização da força de trabalho?",
            "answer": (
                "Indicador mais amplo do que o desemprego: junta desocupados, "
                "subocupados e força de trabalho potencial. Quanto menor, melhor."
            ),
        },
    ]


def glossary_faq_block() -> html.Div:
    accordion_items = [
        dmc.AccordionItem(
            [
                dmc.AccordionControl(
                    dmc.Text(item["question"], fw=700, size="sm"),
                ),
                dmc.AccordionPanel(
                    dmc.Text(item["answer"], size="sm", c="dimmed"),
                ),
            ],
            value=str(item["id"]),
        )
        for item in GLOSSARY_ITEMS
    ]
    sidebar_children = [
        html.Div("?", className="faq-sidebar-icon", **{"aria-hidden": "true"}),
        dmc.Text(
            "O que significa cada indicador?",
            fw=800,
            ta="center",
            style={"color": "white", "lineHeight": 1.25},
        ),
    ]
    if GLOSSARY_FROM_AI:
        sidebar_children.append(
            dmc.Tooltip(
                label="Texto feito com auxílio de IA",
                withArrow=True,
                position="bottom",
                children=html.Span(
                    "✦ IA",
                    className="ai-assist-badge ai-assist-badge--on-dark",
                    role="img",
                    **{"aria-label": "Texto feito com auxílio de IA"},
                ),
            )
        )

    return html.Div(
        className="faq-panel",
        children=[
            html.Div(className="faq-sidebar", children=sidebar_children),
            html.Div(
                className="faq-accordion-wrap",
                children=dmc.Accordion(
                    children=accordion_items,
                    value=str(GLOSSARY_ITEMS[0]["id"]) if GLOSSARY_ITEMS else None,
                    variant="separated",
                    radius="md",
                    chevronPosition="right",
                    className="faq-accordion",
                ),
            ),
        ],
    )


glossary_block = glossary_faq_block()


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
                compare_summary_card(
                    "Taxa de desocupação",
                    "Taxa de desocupação",
                    color=KPI_CARD_COLORS[0],
                ),
                compare_summary_card(
                    "Nível da ocupação",
                    "Nível da ocupação",
                    color=KPI_CARD_COLORS[1],
                ),
                compare_summary_card(
                    "Ocupadas",
                    "Ocupadas",
                    color=KPI_CARD_COLORS[2],
                ),
                compare_summary_card(
                    "Rendimento médio mensal",
                    "Rendimento médio mensal real habitual",
                    color=KPI_CARD_COLORS[3],
                ),
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
                    data=[
                        {"label": indicator_label(item), "value": item}
                        for item in COMPARE_INDICATORS
                    ],
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
                "O sistema regenera a série temporal, o comparativo regional e "
                "os textos de análise (IA gratuita Groq/Gemini, com fallback automático), "
                "e pode publicar os arquivos no GitHub para o Railway redesplegar.",
                size="sm",
                c="dimmed",
                mt="xs",
            ),
            dmc.Alert(
                "Envie somente o quadro sintético do trimestre mais recente "
                "(pnadc_YYYYQQ_...). PDFs mais antigos são rejeitados para não "
                "corromper a série. A análise detalhada do Ceará (setas IBGE) "
                "continua na base curada e não é reescrita automaticamente.",
                color="yellow",
                variant="light",
                mt="md",
                title="Importante",
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

dashboard_shell = html.Div(
    className="app-shell",
    children=[
        header,
        html.Div(
            className="app-main",
            children=dmc.Container(
                size="xl",
                py="md",
                children=[
                    dmc.Group(
                        justify="flex-end",
                        mb="sm",
                        children=[
                            dmc.Button(
                                "Sair",
                                id="logout-btn",
                                variant="light",
                                color="gray",
                                size="xs",
                            ),
                        ],
                    ),
                    dmc.Tabs(
                        value="ceara",
                        className="main-tabs",
                        children=[
                            dmc.TabsList(
                                [
                                    dmc.TabsTab("Ceará", value="ceara"),
                                    dmc.TabsTab("Comparativo", value="comparativo"),
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
        ),
    ],
)


LOGO_SET_URL = "https://set-observatorio.up.railway.app/static/assets/logo_set.png"
LOGO_IDT_URL = "https://set-observatorio.up.railway.app/static/assets/logo_idt.png"


def login_screen() -> html.Div:
    return html.Div(
        className="login-page",
        children=dmc.Paper(
            className="login-card",
            withBorder=True,
            radius="md",
            p=0,
            shadow="md",
            children=[
                html.Div(
                    className="login-logos",
                    children=[
                        html.Img(
                            src=LOGO_SET_URL,
                            alt="Secretaria do Trabalho do Ceará",
                            className="login-logo login-logo--set",
                        ),
                        html.Img(
                            src=LOGO_IDT_URL,
                            alt="Instituto de Desenvolvimento do Trabalho",
                            className="login-logo login-logo--idt",
                        ),
                    ],
                ),
                html.Div(
                    className="login-form",
                    children=[
                        dmc.Title(
                            "PNAD Contínua — Ceará",
                            order=2,
                            ta="center",
                            style={"color": THEME["navy"]},
                        ),
                        dmc.Text(
                            "Acesso restrito ao painel",
                            size="sm",
                            c="dimmed",
                            ta="center",
                            mb="lg",
                            mt="xs",
                        ),
                        dmc.TextInput(
                            id="login-username",
                            label="Usuário",
                            placeholder="Digite o usuário",
                            mb="sm",
                        ),
                        dmc.PasswordInput(
                            id="login-password",
                            label="Senha",
                            placeholder="Digite a senha",
                            mb="md",
                        ),
                        html.Div(id="login-error"),
                        dmc.Button(
                            "Entrar",
                            id="login-btn",
                            fullWidth=True,
                            color="teal",
                            mt="sm",
                        ),
                    ],
                ),
            ],
        ),
    )


def auth_setup_screen() -> html.Div:
    return html.Div(
        className="login-page",
        children=dmc.Alert(
            [
                dmc.Text(
                    "Defina as variáveis de ambiente USUARIO e SENHA no Railway "
                    "(ou localmente) para liberar o acesso ao painel.",
                    size="sm",
                ),
            ],
            title="Login não configurado",
            color="orange",
            className="login-card",
        ),
    )


app.layout = dmc.MantineProvider(
    theme={
        "fontFamily": "Segoe UI, Candara, Calibri, sans-serif",
        "primaryColor": "teal",
        "colors": {
            "teal": [
                "#edf7f4",
                "#d5ebe4",
                "#99CCAA",
                "#72B1A1",
                "#5a9d8d",
                "#1E5A7A",
                "#184d69",
                "#002B49",
                "#001f35",
                "#001526",
            ]
        },
    },
    children=[
        dcc.Location(id="auth-url"),
        dcc.Store(id="auth-refresh", data=0),
        html.Div(id="auth-root"),
    ],
)


@callback(
    Output("auth-root", "children"),
    Input("auth-url", "pathname"),
    Input("auth-refresh", "data"),
)
def render_auth_gate(_pathname, _refresh):
    if not auth_configured():
        return auth_setup_screen()
    if is_logged_in():
        return dashboard_shell
    return login_screen()


@callback(
    Output("auth-refresh", "data"),
    Output("login-error", "children"),
    Input("login-btn", "n_clicks"),
    State("login-username", "value"),
    State("login-password", "value"),
    State("auth-refresh", "data"),
    prevent_initial_call=True,
)
def handle_login(n_clicks, username, password, refresh):
    if not n_clicks:
        return no_update, no_update
    expected_user, expected_pass = auth_credentials()
    user_ok = secrets.compare_digest(str(username or "").strip(), expected_user)
    pass_ok = secrets.compare_digest(str(password or ""), expected_pass)
    if user_ok and pass_ok:
        session["authenticated"] = True
        return (refresh or 0) + 1, None
    return no_update, dmc.Alert(
        "Usuário ou senha inválidos.",
        color="red",
        title="Falha no login",
        mb="sm",
    )


@callback(
    Output("auth-refresh", "data", allow_duplicate=True),
    Input("logout-btn", "n_clicks"),
    State("auth-refresh", "data"),
    prevent_initial_call=True,
)
def handle_logout(n_clicks, refresh):
    if not n_clicks:
        return no_update
    session.pop("authenticated", None)
    return (refresh or 0) + 1


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
        value_text(pd.Series({"valor": float(value), "unidade": unit}))
        for value, unit in zip(table["valor"], table["unidade"], strict=True)
    ]
    table["indicador"] = table["indicador"].map(indicator_label)
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
    if auth_configured() and not is_logged_in():
        return dmc.Alert(
            "Faça login para continuar.",
            color="red",
            title="Não autorizado",
        )
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
