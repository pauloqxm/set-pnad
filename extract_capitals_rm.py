"""Extrai capitais e RMs do Nordeste do quadro sintético PNAD.

Nessas geografias o IBGE publica um quadro reduzido com apenas:
- Taxa de desocupação (%)
- Rendimento médio mensal real habitual (R$)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd
import pdfplumber

import extract_regional

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_CSV = BASE_DIR / "data" / "pnad_capitais_rm_nordeste.csv"
AUDIT_JSON = BASE_DIR / "data" / "capitais_rm_extraction_audit.json"

# Ordem oficial do Nordeste no quadro sintético.
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

# Correções conhecidas do texto extraído do PDF (ex.: Fortaleza aparece como PI).
GEO_UF_FIXES = {
    "Fortaleza": "CE",
}


def parse_num(value: str) -> float:
    value = (value or "").strip().replace("\xa0", " ")
    if not value or value == "-":
        raise ValueError(f"número inválido: {value!r}")
    # Formato rendimento em município/RM: "3 489" (espaço como milhar).
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
    match = re.search(r"Maio de \d{4}\s+([^\n]+)", text)
    return match.group(1).strip() if match else None


def metrics_from_table(page) -> dict[str, float]:
    tables = page.extract_tables() or []
    if not tables:
        return {}
    metrics: dict[str, float] = {}
    for row in tables[0]:
        cells = [(" ".join(c.split()) if isinstance(c, str) else c) for c in row]
        joined = " | ".join(str(c) for c in cells if c)
        if "Taxa de desocupação" in joined or "Taxa de desocupa" in joined:
            # Colunas: ... | t-2 | t-1 | t | situação | ...
            values = [c for c in cells if isinstance(c, str) and re.fullmatch(r"-?[\d.,]+", c)]
            if len(values) >= 3:
                metrics["Taxa de desocupação"] = parse_num(values[2])
        if any(isinstance(c, str) and c.strip() == "Total" for c in cells):
            values = [c for c in cells if isinstance(c, str) and re.fullmatch(r"-?[\d. ]+", c)]
            # Rendimento: "3 489", "3 600", "3 780" — pegar o trimestre atual (3º).
            money = [c for c in cells if isinstance(c, str) and re.fullmatch(r"\d{1,3}(?: \d{3})+", c)]
            if len(money) >= 3:
                metrics["Rendimento médio mensal real habitual"] = parse_num(money[2])
            elif len(values) >= 3:
                try:
                    metrics["Rendimento médio mensal real habitual"] = parse_num(values[2])
                except ValueError:
                    pass
    return metrics


def is_northeast_capital_or_rm(name: str) -> bool:
    return any(city in name for city in NORTHEAST_CAPITAL_KEYS)


def build_dataframe(pdf_path: Path) -> tuple[pd.DataFrame, dict]:
    records: list[dict] = []
    audit_geos: list[dict] = []
    latest_period = None

    with pdfplumber.open(pdf_path) as pdf:
        for index, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if "Taxa de desocupação" not in text and "Taxa de desocupa" not in text:
                continue
            raw_geo = extract_geo_header(text)
            if not raw_geo:
                continue
            if not is_northeast_capital_or_rm(raw_geo):
                continue
            # Páginas de estado/região são longas; capitais/RM têm quadro reduzido.
            if "Nível da ocupação" in text or "Nivel da ocupacao" in text:
                continue

            geografia, uf, tipo, curto = normalize_geo_name(raw_geo)
            if uf not in NORTHEAST_UF_ORDER:
                continue

            metrics = metrics_from_table(page)
            period = extract_period(text) or latest_period
            if period:
                latest_period = period

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
            for indicador, unidade in (
                ("Taxa de desocupação", "%"),
                ("Rendimento médio mensal real habitual", "R$"),
            ):
                if indicador not in metrics:
                    continue
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
                        "valor": metrics[indicador],
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
    # Ordena: UF nordestina, capital antes de RM, indicador.
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
            "UF de Fortaleza é forçada para CE quando o PDF extrai PI."
        ),
    }
    return frame.reset_index(drop=True), audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, help="Caminho do quadro sintético")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = extract_regional.resolve_pdf(args.pdf)
    frame, audit = build_dataframe(pdf_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, encoding="utf-8-sig", float_format="%.1f")
    AUDIT_JSON.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CSV capitais/RMs criado: {args.output} ({len(frame)} linhas)")


if __name__ == "__main__":
    main()
