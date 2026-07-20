"""Extrai capitais e RMs do Nordeste do quadro sintético PNAD.

Nessas geografias o IBGE publica um quadro reduzido com apenas:
- Taxa de desocupação (%)
- Rendimento médio mensal real habitual (R$)

Também monta a série temporal (trimestre atual + 3 anteriores) para
Fortaleza e RM Fortaleza a partir dos PDFs em pnad/.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd
import pdfplumber

import extract_regional
import extract_series

BASE_DIR = Path(__file__).resolve().parent
PNAD_DIR = BASE_DIR / "pnad"
OUTPUT_CSV = BASE_DIR / "data" / "pnad_capitais_rm_nordeste.csv"
OUTPUT_SERIE_CSV = BASE_DIR / "data" / "pnad_capitais_rm_serie.csv"
AUDIT_JSON = BASE_DIR / "data" / "capitais_rm_extraction_audit.json"
SERIE_AUDIT_JSON = BASE_DIR / "data" / "capitais_rm_serie_audit.json"

NORTHEAST_UF_ORDER = ("MA", "PI", "CE", "RN", "PB", "PE", "AL", "SE", "BA")

NORTHEAST_CAPITAL_KEYS = {
    "São Luís": "MA",
    "Teresina": "PI",
    "Fortaleza": "CE",
    "Natal": "RN",
    "João Pessoa": "PB",
    "Recife": "PE",
    "Maceió": "AL",
    "Aracaju": "SE",
    "Salvador": "BA",
}

GEO_UF_FIXES = {
    "Fortaleza": "CE",
}

SERIE_LOCAIS = ("Fortaleza", "RM Fortaleza")
INDICATOR_UNITS = (
    ("Taxa de desocupação", "%"),
    ("Rendimento médio mensal real habitual", "R$"),
)


def parse_num(value: str) -> float:
    value = (value or "").strip().replace("\xa0", " ")
    if not value or value == "-":
        raise ValueError(f"número inválido: {value!r}")
    if " " in value and "," not in value:
        return float(value.replace(" ", ""))
    if "," in value:
        return float(value.replace(".", "").replace(",", "."))
    return float(value)


def normalize_geo_name(raw: str) -> tuple[str, str, str, str]:
    """Retorna (geografia, uf, tipo, nome_curto)."""
    name = " ".join((raw or "").split())
    uf_match = re.search(r"\(([A-Z]{2})\)\s*$", name)
    uf = uf_match.group(1) if uf_match else ""

    is_rm = name.lower().startswith("região metropolitana") or name.lower().startswith(
        "regiao metropolitana"
    )
    tipo = "rm" if is_rm else "capital"

    short = name
    for city, expected_uf in NORTHEAST_CAPITAL_KEYS.items():
        if city in name:
            short = city if tipo == "capital" else f"RM {city}"
            uf = GEO_UF_FIXES.get(city, expected_uf)
            break

    if uf and not name.endswith(f"({uf})"):
        name = re.sub(r"\([A-Z]{2}\)\s*$", f"({uf})", name)

    return name, uf, tipo, short


def extract_period(text: str) -> str | None:
    match = re.search(r"Trimestre(?: móvel)?:\s*([^\n]+)", text)
    return match.group(1).strip() if match else None


def extract_geo_header(text: str) -> str | None:
    match = re.search(
        r"Divulgação:\s+\S+\s+de\s+\d{4}\s+([^\n]+)",
        text,
    )
    if match:
        return match.group(1).strip()
    match = re.search(
        r"de \d{4}\s+((?:Município|Municipio|Região Metropolitana|Regiao Metropolitana)[^\n]+)",
        text,
    )
    return match.group(1).strip() if match else None


def _estimate_triples(row_cells: list) -> tuple[float, float, float] | None:
    """Extrai (ano_anterior, tri_anterior, atual) de uma linha da tabela."""
    money = [
        c
        for c in row_cells
        if isinstance(c, str) and re.fullmatch(r"\d{1,3}(?: \d{3})+", c)
    ]
    if len(money) >= 3:
        return parse_num(money[0]), parse_num(money[1]), parse_num(money[2])

    values = [
        c
        for c in row_cells
        if isinstance(c, str) and re.fullmatch(r"-?[\d.,]+", c)
    ]
    if len(values) >= 3:
        return parse_num(values[0]), parse_num(values[1]), parse_num(values[2])
    return None


def metrics_from_table(page) -> dict[str, dict[str, float]]:
    """Retorna indicador -> {atual, ano_anterior, tri_anterior}."""
    tables = page.extract_tables() or []
    if not tables:
        return {}
    metrics: dict[str, dict[str, float]] = {}
    for row in tables[0]:
        cells = [(" ".join(c.split()) if isinstance(c, str) else c) for c in row]
        joined = " | ".join(str(c) for c in cells if c)
        if "Taxa de desocupação" in joined or "Taxa de desocupa" in joined:
            triple = _estimate_triples(cells)
            if triple:
                ano, tri, atual = triple
                metrics["Taxa de desocupação"] = {
                    "atual": atual,
                    "ano_anterior": ano,
                    "tri_anterior": tri,
                }
        if any(isinstance(c, str) and c.strip() == "Total" for c in cells):
            triple = _estimate_triples(cells)
            if triple:
                ano, tri, atual = triple
                metrics["Rendimento médio mensal real habitual"] = {
                    "atual": atual,
                    "ano_anterior": ano,
                    "tri_anterior": tri,
                }
    return metrics


def is_northeast_capital_or_rm(name: str) -> bool:
    return any(city in name for city in NORTHEAST_CAPITAL_KEYS)


def iter_capital_rm_pages(pdf_path: Path):
    with pdfplumber.open(pdf_path) as pdf:
        for index, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if "Taxa de desocupação" not in text and "Taxa de desocupa" not in text:
                continue
            raw_geo = extract_geo_header(text)
            if not raw_geo or not is_northeast_capital_or_rm(raw_geo):
                continue
            if "Nível da ocupação" in text or "Nivel da ocupacao" in text:
                continue
            geografia, uf, tipo, curto = normalize_geo_name(raw_geo)
            if uf not in NORTHEAST_UF_ORDER:
                continue
            yield index, page, text, geografia, uf, tipo, curto


def build_dataframe(pdf_path: Path) -> tuple[pd.DataFrame, dict]:
    records: list[dict] = []
    audit_geos: list[dict] = []
    latest_period = None

    for index, page, text, geografia, uf, tipo, curto in iter_capital_rm_pages(pdf_path):
        metrics = metrics_from_table(page)
        period = extract_period(text) or latest_period
        if period:
            latest_period = period

        flat_metrics = {name: vals["atual"] for name, vals in metrics.items()}
        audit_geos.append(
            {
                "pagina": index + 1,
                "geografia": geografia,
                "uf": uf,
                "tipo": tipo,
                "metricas": metrics,
            }
        )

        destaque = "Fortaleza" in geografia
        for indicador, unidade in INDICATOR_UNITS:
            if indicador not in metrics:
                continue
            vals = metrics[indicador]
            records.append(
                {
                    "geografia": geografia,
                    "nome_curto": curto,
                    "uf": uf,
                    "tipo": tipo,
                    "grupo_geografico": (
                        "Região metropolitana" if tipo == "rm" else "Capital"
                    ),
                    "indicador": indicador,
                    "unidade": unidade,
                    "periodo": latest_period or "trimestre atual",
                    "valor": vals["atual"],
                    "valor_ano_anterior": vals["ano_anterior"],
                    "destaque_ceara": destaque,
                    "fonte": "IBGE, PNAD Contínua Trimestral — quadro sintético (capitais/RMs)",
                }
            )

    if not records:
        raise ValueError("Nenhuma capital/RM do Nordeste encontrada no PDF.")

    expected = set(NORTHEAST_CAPITAL_KEYS.values())
    found_ufs = {row["uf"] for row in records}
    missing = sorted(expected - found_ufs)
    if missing:
        raise ValueError(f"UFs do Nordeste sem capital/RM no PDF: {missing}")

    frame = pd.DataFrame.from_records(records)
    tipo_rank = {"capital": 0, "rm": 1}
    uf_rank = {uf: i for i, uf in enumerate(NORTHEAST_UF_ORDER)}
    frame["_uf"] = frame["uf"].map(uf_rank)
    frame["_tipo"] = frame["tipo"].map(tipo_rank)
    frame = frame.sort_values(["_uf", "_tipo", "indicador"]).drop(columns=["_uf", "_tipo"])

    audit = {
        "arquivo_pdf": str(pdf_path.resolve()),
        "periodo": latest_period,
        "geografias": audit_geos,
        "linhas_csv": len(frame),
        "nota": (
            "Quadro reduzido: só taxa de desocupação e rendimento médio. "
            "UF de Fortaleza é forçada para CE quando o PDF extrai PI. "
            "valor_ano_anterior = mesma trimestre do ano anterior (1ª coluna)."
        ),
    }
    return frame.reset_index(drop=True), audit


def extract_focus_metrics(pdf_path: Path) -> dict[str, dict[str, dict[str, float]]]:
    """Extrai métricas só de Fortaleza e RM Fortaleza."""
    found: dict[str, dict[str, dict[str, float]]] = {}
    for _index, page, _text, _geo, _uf, _tipo, curto in iter_capital_rm_pages(pdf_path):
        if curto not in SERIE_LOCAIS:
            continue
        metrics = metrics_from_table(page)
        if metrics:
            found[curto] = metrics
        if len(found) == len(SERIE_LOCAIS):
            break
    return found


def build_series(folder: Path | None = None, *, last_n: int = 4) -> tuple[pd.DataFrame, dict]:
    folder = folder or PNAD_DIR
    pdfs = extract_series.list_quadro_pdfs(folder)
    if not pdfs:
        fallback = extract_regional.resolve_pdf(None)
        label, _year, _q, order = extract_series.period_from_code(
            re.search(r"pnadc_(\d{6})_", fallback.name, re.I).group(1)
        )
        pdfs = [(fallback, re.search(r"pnadc_(\d{6})_", fallback.name, re.I).group(1), label, order)]

    selected = pdfs[-last_n:]
    records: list[dict] = []
    for path, code, label, order in selected:
        focus = extract_focus_metrics(path)
        for curto in SERIE_LOCAIS:
            metrics = focus.get(curto)
            if not metrics:
                continue
            for indicador, unidade in INDICATOR_UNITS:
                if indicador not in metrics:
                    continue
                records.append(
                    {
                        "codigo_trimestre": code,
                        "periodo": label,
                        "ordem_periodo": order,
                        "nome_curto": curto,
                        "indicador": indicador,
                        "unidade": unidade,
                        "valor": metrics[indicador]["atual"],
                        "arquivo_pdf": path.name,
                        "fonte": "IBGE, PNAD Contínua Trimestral — quadro sintético (capitais/RMs)",
                    }
                )

    if not records:
        raise ValueError("Não foi possível montar série de Fortaleza/RM a partir dos PDFs.")

    frame = pd.DataFrame.from_records(records).sort_values(
        ["ordem_periodo", "nome_curto", "indicador"]
    )
    audit = {
        "pasta": str(folder.resolve()),
        "arquivos_usados": [path.name for path, *_ in selected],
        "periodos": frame["periodo"].drop_duplicates().tolist(),
        "locais": list(SERIE_LOCAIS),
        "linhas_csv": len(frame),
    }
    return frame.reset_index(drop=True), audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, help="Caminho do quadro sintético (snapshot)")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV)
    parser.add_argument("--serie-output", type=Path, default=OUTPUT_SERIE_CSV)
    parser.add_argument("--last-n", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = extract_regional.resolve_pdf(args.pdf)
    frame, audit = build_dataframe(pdf_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, encoding="utf-8-sig", float_format="%.1f")
    AUDIT_JSON.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CSV capitais/RMs criado: {args.output} ({len(frame)} linhas)")

    serie, serie_audit = build_series(PNAD_DIR, last_n=args.last_n)
    args.serie_output.parent.mkdir(parents=True, exist_ok=True)
    serie.to_csv(args.serie_output, index=False, encoding="utf-8-sig", float_format="%.1f")
    SERIE_AUDIT_JSON.write_text(
        json.dumps(serie_audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Série Fortaleza/RM criada: {args.serie_output} ({len(serie)} linhas)")


if __name__ == "__main__":
    main()
