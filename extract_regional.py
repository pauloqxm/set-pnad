"""Extrai indicadores comparáveis do quadro sintético PNAD (Brasil e Nordeste)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd
import pdfplumber

BASE_DIR = Path(__file__).resolve().parent
PNAD_DIR = BASE_DIR / "pnad"
OUTPUT_CSV = BASE_DIR / "data" / "pnad_comparativo_1tri2026.csv"
AUDIT_JSON = BASE_DIR / "data" / "regional_extraction_audit.json"

MACRO_REGIONS = ("Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul")
NORTHEAST_STATES = (
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
COMPARISON_GEOS = ("Brasil", "Nordeste", *NORTHEAST_STATES)

INDICATORS = (
    ("Taxa de desocupação", "%", r"Taxa de desocupação\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)"),
    ("Nível da ocupação", "%", r"Nível da ocupação\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)"),
    (
        "Taxa de participação na força de trabalho",
        "%",
        r"Taxa de participação na força de trabalho\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
    ),
    ("Ocupadas", "Mil pessoas", r"\bOcupada[s]?\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)"),
    ("Desocupadas", "Mil pessoas", r"\bDesocupada[s]?\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)"),
    ("Pessoas de 14 anos ou mais", "Mil pessoas", r"\bTotal\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)"),
    (
        "Taxa composta de subutilização da força de trabalho",
        "%",
        r"Taxa composta de subutilização da força de trabalho\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
    ),
)


def parse_num(value: str) -> float:
    value = value.strip()
    if "," in value:
        return float(value.replace(".", "").replace(",", "."))
    return float(value.replace(".", ""))


def resolve_pdf(requested: Path | None) -> Path:
    if requested and requested.is_file():
        return requested

    pnad_files = sorted(PNAD_DIR.glob("pnadc_*_trimestre_quadroSintetico.pdf"))
    if pnad_files:
        return pnad_files[-1]

    fallbacks = [
        BASE_DIR / "pnadc_202601_trimestre_quadroSintetico.pdf",
        BASE_DIR / "data" / "pnadc_202601_trimestre_quadroSintetico.pdf",
    ]
    for candidate in fallbacks:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Quadro sintético não encontrado. Coloque os PDFs em pnad/ "
        "(pnadc_YYYYQQ_trimestre_quadroSintetico.pdf)."
    )


def extract_geo_name(text: str) -> str | None:
    match = re.search(r"Divulgação:\s+\S+\s+de\s+\d{4}\s+([^\n]+)", text)
    return match.group(1).strip() if match else None


def extract_period(text: str) -> str | None:
    match = re.search(r"Trimestre móvel:\s*([^\n]+)", text)
    return match.group(1).strip() if match else None


def latest_value(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return parse_num(match.group(3))


def extract_rendimento(text: str) -> tuple[float | None, float | None]:
    totals = re.findall(r"Total\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", text)
    if len(totals) < 2:
        return None, None
    return parse_num(totals[-2][2]), parse_num(totals[-1][2])


def extract_geo_metrics(main_text: str, sub_text: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for name, _, pattern in INDICATORS:
        if name == "Taxa composta de subutilização da força de trabalho":
            value = latest_value(sub_text, pattern)
        else:
            value = latest_value(main_text, pattern)
        if value is not None:
            metrics[name] = value
    medio, massa = extract_rendimento(main_text)
    if medio is not None:
        metrics["Rendimento médio mensal real habitual"] = medio
    if massa is not None:
        metrics["Massa de rendimento mensal real habitual"] = massa
    return metrics


def aggregate_brazil(region_metrics: dict[str, dict[str, float]]) -> dict[str, float]:
    totals = {
        "Pessoas de 14 anos ou mais": 0.0,
        "Ocupadas": 0.0,
        "Desocupadas": 0.0,
    }
    for region in MACRO_REGIONS:
        data = region_metrics[region]
        for key in totals:
            totals[key] += data[key]

    forca = totals["Ocupadas"] + totals["Desocupadas"]
    return {
        "Taxa de desocupação": totals["Desocupadas"] / forca * 100 if forca else 0.0,
        "Nível da ocupação": totals["Ocupadas"] / totals["Pessoas de 14 anos ou mais"] * 100
        if totals["Pessoas de 14 anos ou mais"]
        else 0.0,
        "Taxa de participação na força de trabalho": forca / totals["Pessoas de 14 anos ou mais"] * 100
        if totals["Pessoas de 14 anos ou mais"]
        else 0.0,
        "Ocupadas": totals["Ocupadas"],
        "Desocupadas": totals["Desocupadas"],
        "Pessoas de 14 anos ou mais": totals["Pessoas de 14 anos ou mais"],
        "Rendimento médio mensal real habitual": sum(
            region_metrics[r]["Rendimento médio mensal real habitual"] * region_metrics[r]["Ocupadas"]
            for r in MACRO_REGIONS
        )
        / totals["Ocupadas"]
        if totals["Ocupadas"]
        else 0.0,
        "Massa de rendimento mensal real habitual": sum(
            region_metrics[r]["Massa de rendimento mensal real habitual"] for r in MACRO_REGIONS
        ),
        "Taxa composta de subutilização da força de trabalho": sum(
            region_metrics[r]["Taxa composta de subutilização da força de trabalho"]
            * region_metrics[r]["Pessoas de 14 anos ou mais"]
            for r in MACRO_REGIONS
        )
        / totals["Pessoas de 14 anos ou mais"]
        if totals["Pessoas de 14 anos ou mais"]
        else 0.0,
    }


def build_dataframe(pdf_path: Path) -> tuple[pd.DataFrame, dict]:
    geo_pages: dict[str, tuple[str, str]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for index, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if "Indicadores de subutilização" in text:
                continue
            if "Taxa de desocupação" not in text:
                continue
            geo = extract_geo_name(text)
            if not geo:
                continue
            sub_text = ""
            if index + 1 < len(pdf.pages):
                sub_text = pdf.pages[index + 1].extract_text() or ""
            geo_pages[geo] = (text, sub_text)

    region_metrics: dict[str, dict[str, float]] = {}
    northeast_metrics: dict[str, dict[str, float]] = {}
    for geo, (main_text, sub_text) in geo_pages.items():
        metrics = extract_geo_metrics(main_text, sub_text)
        if geo in MACRO_REGIONS:
            region_metrics[geo] = metrics
        if geo in NORTHEAST_STATES:
            northeast_metrics[geo] = metrics

    missing_regions = [region for region in MACRO_REGIONS if region not in region_metrics]
    if missing_regions:
        raise ValueError(f"Regiões macro ausentes no PDF: {missing_regions}")

    missing_states = [state for state in NORTHEAST_STATES if state not in northeast_metrics]
    if missing_states:
        raise ValueError(f"Estados do Nordeste ausentes no PDF: {missing_states}")

    all_metrics = {
        "Brasil": aggregate_brazil(region_metrics),
        "Nordeste": region_metrics["Nordeste"],
        **{state: northeast_metrics[state] for state in NORTHEAST_STATES},
    }

    sample_text = geo_pages.get("Ceará", geo_pages.get("Nordeste", ("", "")))[0]
    latest_period = extract_period(sample_text) or "trimestre atual"

    records: list[dict] = []
    for geo in COMPARISON_GEOS:
        grupo = "Brasil" if geo == "Brasil" else "Nordeste" if geo == "Nordeste" else "Estados do Nordeste"
        destaque = geo == "Ceará"
        for name, unit, _ in INDICATORS:
            records.append(
                {
                    "geografia": geo,
                    "grupo_geografico": grupo,
                    "indicador": name,
                    "unidade": unit,
                    "periodo": latest_period,
                    "valor": all_metrics[geo][name],
                    "destaque_ceara": destaque,
                    "fonte": "IBGE, PNAD Contínua Trimestral — quadro sintético",
                }
            )
        for extra in ("Rendimento médio mensal real habitual", "Massa de rendimento mensal real habitual"):
            unit = "R$" if extra.startswith("Rendimento médio") else "R$ milhões"
            records.append(
                {
                    "geografia": geo,
                    "grupo_geografico": grupo,
                    "indicador": extra,
                    "unidade": unit,
                    "periodo": latest_period,
                    "valor": all_metrics[geo][extra],
                    "destaque_ceara": destaque,
                    "fonte": "IBGE, PNAD Contínua Trimestral — quadro sintético",
                }
            )

    frame = pd.DataFrame.from_records(records)
    audit = {
        "arquivo_pdf": str(pdf_path.resolve()),
        "periodo": latest_period,
        "geografias": list(COMPARISON_GEOS),
        "linhas_csv": len(frame),
        "regioes_macro": {geo: region_metrics[geo] for geo in MACRO_REGIONS},
        "brasil_agregado": all_metrics["Brasil"],
    }
    return frame, audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, help="Caminho do quadro sintético")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = resolve_pdf(args.pdf)
    frame, audit = build_dataframe(pdf_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, encoding="utf-8-sig", float_format="%.1f")
    AUDIT_JSON.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CSV comparativo criado: {args.output} ({len(frame)} linhas)")


if __name__ == "__main__":
    main()
