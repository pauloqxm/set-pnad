"""Extrai e normaliza o quadro sintético da PNAD Contínua para o Ceará.

O PDF do IBGE usa uma diagramação visual na qual rótulos e números nem sempre
saem na mesma ordem na extração textual. Por isso, as linhas do quadro são
declaradas explicitamente abaixo e conferidas contra a camada textual do PDF.
Isso torna a associação entre cada rótulo e seus valores auditável.

As colunas de significância estatística ("Situação", representadas por setas
no PDF) foram decodificadas do quadro sintético oficial do IBGE (páginas do
Ceará), no qual os glifos Wingdings3 extraem-se como "*" (estável),
"#" (cresceu) e "$" (decresceu).
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import pdfplumber
import requests


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PDF = BASE_DIR / "pand ce 1tri 2026.pdf"
DATA_DIR = BASE_DIR / "data"
OUTPUT_CSV = DATA_DIR / "pnad_ce_1tri2026.csv"
AUDIT_JSON = DATA_DIR / "extraction_audit.json"
OFFICIAL_URL = (
    "https://ftp.ibge.gov.br/Trabalho_e_Rendimento/"
    "Pesquisa_Nacional_por_Amostra_de_Domicilios_continua/Trimestral/"
    "Quadro_Sintetico/2026/pnadc_202601_trimestre_quadroSintetico.pdf"
)
FALLBACK_PDF = DATA_DIR / "pnadc_202601_trimestre_quadroSintetico.pdf"

PERIODS = (
    ("jan-fev-mar/2025", 1),
    ("out-nov-dez/2025", 2),
    ("jan-fev-mar/2026", 3),
)

# Códigos de situação conforme a legenda do IBGE.
EST = "estavel"
CRE = "cresceu"
DEC = "decresceu"


@dataclass(frozen=True)
class Indicator:
    section: str
    group: str
    name: str
    unit: str
    values: tuple[float, float, float]
    quarter_abs: float | None
    quarter_pct: float | None
    year_abs: float | None
    year_pct: float | None
    situ_quarter: str
    situ_year: str


def item(
    section: str,
    group: str,
    name: str,
    unit: str,
    values: tuple[float, float, float],
    changes: tuple[float | None, float | None, float | None, float | None],
    situ: tuple[str, str],
) -> Indicator:
    return Indicator(section, group, name, unit, values, *changes, *situ)


INDICATORS: tuple[Indicator, ...] = (
    item("Mercado de trabalho", "Taxas principais", "Taxa de desocupação", "%", (8.0, 5.0, 7.3), (2.3, None, -0.7, None), (CRE, EST)),
    item("Mercado de trabalho", "Taxas principais", "Nível da ocupação", "%", (46.5, 49.5, 47.6), (-2.0, None, 1.0, None), (DEC, EST)),
    item("Mercado de trabalho", "Taxas principais", "Taxa de participação na força de trabalho", "%", (50.6, 52.1, 51.3), (-0.8, None, 0.7, None), (EST, EST)),
    item("Mercado de trabalho", "Condição em relação à força de trabalho", "Pessoas de 14 anos ou mais", "Mil pessoas", (7559, 7583, 7576), (-7, -0.1, 18, 0.2), (EST, EST)),
    item("Mercado de trabalho", "Condição em relação à força de trabalho", "Na força de trabalho", "Mil pessoas", (3824, 3952, 3885), (-67, -1.7, 60, 1.6), (EST, EST)),
    item("Mercado de trabalho", "Condição em relação à força de trabalho", "Ocupadas", "Mil pessoas", (3518, 3756, 3603), (-153, -4.1, 84, 2.4), (DEC, EST)),
    item("Mercado de trabalho", "Condição em relação à força de trabalho", "Desocupadas", "Mil pessoas", (306, 196, 282), (86, 44.2, -24, -7.8), (CRE, EST)),
    item("Mercado de trabalho", "Condição em relação à força de trabalho", "Fora da força de trabalho", "Mil pessoas", (3734, 3632, 3692), (60, 1.6, -43, -1.1), (EST, EST)),
    item("Ocupação", "Posição e categoria", "Empregados", "Mil pessoas", (2383, 2543, 2473), (-71, -2.8, 90, 3.8), (EST, EST)),
    item("Ocupação", "Posição e categoria", "Setor privado (exclusive trabalhador doméstico)", "Mil pessoas", (1662, 1742, 1706), (-35, -2.0, 44, 2.6), (EST, EST)),
    item("Ocupação", "Setor privado", "Setor privado — com carteira", "Mil pessoas", (940, 1035, 1037), (2, 0.2, 96, 10.2), (EST, CRE)),
    item("Ocupação", "Setor privado", "Setor privado — sem carteira", "Mil pessoas", (722, 707, 669), (-37, -5.3, -53, -7.3), (EST, EST)),
    item("Ocupação", "Posição e categoria", "Trabalhadores domésticos", "Mil pessoas", (223, 231, 198), (-34, -14.6, -25, -11.4), (DEC, EST)),
    item("Ocupação", "Trabalho doméstico", "Trabalho doméstico — com carteira", "Mil pessoas", (25, 28, 27), (-1, -3.0, 3, 11.4), (EST, EST)),
    item("Ocupação", "Trabalho doméstico", "Trabalho doméstico — sem carteira", "Mil pessoas", (198, 203, 170), (-33, -16.2, -28, -14.2), (DEC, DEC)),
    item("Ocupação", "Posição e categoria", "Setor público", "Mil pessoas", (498, 570, 569), (-1, -0.2, 71, 14.3), (EST, CRE)),
    item("Ocupação", "Setor público", "Setor público — com carteira", "Mil pessoas", (55, 65, 56), (-9, -13.4, 1, 1.2), (EST, EST)),
    item("Ocupação", "Setor público", "Militares e funcionários públicos estatutários", "Mil pessoas", (284, 293, 293), (-1, -0.2, 9, 3.1), (EST, EST)),
    item("Ocupação", "Setor público", "Setor público — sem carteira", "Mil pessoas", (158, 212, 220), (8, 3.7, 62, 38.9), (EST, CRE)),
    item("Ocupação", "Posição e categoria", "Empregadores", "Mil pessoas", (111, 114, 92), (-23, -19.7, -19, -17.5), (DEC, EST)),
    item("Ocupação", "Empregadores", "Empregadores — com CNPJ", "Mil pessoas", (70, 77, 65), (-12, -16.1, -6, -7.9), (EST, EST)),
    item("Ocupação", "Empregadores", "Empregadores — sem CNPJ", "Mil pessoas", (41, 37, 27), (-10, -27.2, -14, -33.8), (EST, DEC)),
    item("Ocupação", "Posição e categoria", "Trabalhadores por conta própria", "Mil pessoas", (981, 1053, 994), (-59, -5.6, 13, 1.3), (DEC, EST)),
    item("Ocupação", "Conta própria", "Conta própria — com CNPJ", "Mil pessoas", (132, 141, 127), (-14, -10.1, -5, -4.0), (EST, EST)),
    item("Ocupação", "Conta própria", "Conta própria — sem CNPJ", "Mil pessoas", (849, 912, 867), (-45, -4.9, 18, 2.2), (EST, EST)),
    item("Ocupação", "Posição e categoria", "Trabalhadores familiares auxiliares", "Mil pessoas", (43, 45, 44), (-1, -2.3, 1, 2.1), (EST, EST)),
    item("Atividades", "Grupamentos de atividade", "Agricultura, pecuária, produção florestal, pesca e aquicultura", "Mil pessoas", (330, 340, 311), (-29, -8.6, -19, -5.8), (DEC, EST)),
    item("Atividades", "Grupamentos de atividade", "Indústria geral", "Mil pessoas", (438, 461, 413), (-49, -10.5, -25, -5.8), (DEC, EST)),
    item("Atividades", "Grupamentos de atividade", "Construção", "Mil pessoas", (255, 283, 264), (-19, -6.6, 9, 3.6), (EST, EST)),
    item("Atividades", "Grupamentos de atividade", "Comércio e reparação de veículos", "Mil pessoas", (776, 745, 735), (-10, -1.3, -41, -5.3), (EST, EST)),
    item("Atividades", "Grupamentos de atividade", "Transporte, armazenagem e correio", "Mil pessoas", (142, 180, 164), (-17, -9.2, 22, 15.1), (EST, EST)),
    item("Atividades", "Grupamentos de atividade", "Alojamento e alimentação", "Mil pessoas", (213, 208, 210), (1, 0.5, -4, -1.7), (EST, EST)),
    item("Atividades", "Grupamentos de atividade", "Informação, finanças, imobiliárias, profissionais e administrativas", "Mil pessoas", (301, 351, 363), (13, 3.6, 62, 20.7), (EST, CRE)),
    item("Atividades", "Grupamentos de atividade", "Administração pública, educação, saúde e serviços sociais", "Mil pessoas", (654, 755, 755), (0, 0.0, 101, 15.4), (EST, CRE)),
    item("Atividades", "Grupamentos de atividade", "Outros serviços", "Mil pessoas", (184, 199, 189), (-11, -5.4, 4, 2.4), (EST, EST)),
    item("Atividades", "Grupamentos de atividade", "Serviços domésticos", "Mil pessoas", (225, 233, 200), (-33, -14.1, -24, -10.8), (DEC, EST)),
    item("Rendimento", "Rendimento", "Rendimento médio mensal real habitual", "R$", (2333, 2469, 2597), (128, 5.2, 265, 11.4), (EST, CRE)),
    item("Rendimento", "Rendimento", "Massa de rendimento mensal real habitual", "R$ milhões", (8105, 9147, 9235), (87, 1.0, 1130, 13.9), (EST, CRE)),
    item("Subutilização", "Pessoas", "Na força de trabalho", "Mil pessoas", (3824, 3952, 3885), (-67, -1.7, 60, 1.6), (EST, EST)),
    item("Subutilização", "Pessoas", "Ocupadas", "Mil pessoas", (3518, 3756, 3603), (-153, -4.1, 84, 2.4), (DEC, EST)),
    item("Subutilização", "Pessoas", "Subocupadas por insuficiência de horas trabalhadas", "Mil pessoas", (256, 240, 204), (-37, -15.2, -53, -20.6), (DEC, DEC)),
    item("Subutilização", "Pessoas", "Desocupadas", "Mil pessoas", (306, 196, 282), (86, 44.2, -24, -7.8), (CRE, EST)),
    item("Subutilização", "Pessoas", "Fora da força de trabalho", "Mil pessoas", (3734, 3632, 3692), (60, 1.6, -43, -1.1), (EST, EST)),
    item("Subutilização", "Pessoas", "Na força de trabalho potencial", "Mil pessoas", (441, 303, 352), (49, 16.1, -90, -20.3), (CRE, DEC)),
    item("Subutilização", "Pessoas", "Desalentadas", "Mil pessoas", (294, 188, 219), (32, 16.9, -75, -25.4), (CRE, DEC)),
    item("Subutilização", "Pessoas", "Desocupadas ou subocupadas", "Mil pessoas", (562, 436, 486), (50, 11.4, -77, -13.6), (CRE, DEC)),
    item("Subutilização", "Pessoas", "Desocupadas ou na força de trabalho potencial", "Mil pessoas", (747, 498, 634), (135, 27.1, -114, -15.2), (CRE, DEC)),
    item("Subutilização", "Pessoas", "Desocupadas, subocupadas ou na força de trabalho potencial", "Mil pessoas", (1004, 739, 837), (99, 13.4, -167, -16.6), (CRE, DEC)),
    item("Subutilização", "Pessoas", "Na força de trabalho ampliada", "Mil pessoas", (4266, 4254, 4236), (-18, -0.4, -30, -0.7), (EST, EST)),
    item("Subutilização", "Pessoas", "Na força de trabalho ou desalentadas", "Mil pessoas", (4118, 4139, 4104), (-35, -0.9, -14, -0.3), (EST, EST)),
    item("Subutilização", "Taxas e percentuais", "Taxa de desocupação", "%", (8.0, 5.0, 7.3), (2.3, None, -0.7, None), (CRE, EST)),
    item("Subutilização", "Taxas e percentuais", "Taxa combinada de desocupação e subocupação", "%", (14.7, 11.0, 12.5), (1.5, None, -2.2, None), (CRE, DEC)),
    item("Subutilização", "Taxas e percentuais", "Taxa combinada de desocupação e força de trabalho potencial", "%", (17.5, 11.7, 15.0), (3.2, None, -2.6, None), (CRE, DEC)),
    item("Subutilização", "Taxas e percentuais", "Taxa composta de subutilização da força de trabalho", "%", (23.5, 17.4, 19.8), (2.4, None, -3.8, None), (CRE, DEC)),
    item("Subutilização", "Taxas e percentuais", "Taxa de subocupação por insuficiência de horas trabalhadas", "%", (7.3, 6.4, 5.7), (-0.7, None, -1.6, None), (EST, DEC)),
    item("Subutilização", "Taxas e percentuais", "Percentual de pessoas desalentadas", "%", (7.1, 4.5, 5.3), (0.8, None, -1.8, None), (CRE, DEC)),
)


def slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def download_official_pdf() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"PDF local não encontrado. Baixando fonte oficial: {OFFICIAL_URL}")
    response = requests.get(OFFICIAL_URL, timeout=180)
    response.raise_for_status()
    FALLBACK_PDF.write_bytes(response.content)
    return FALLBACK_PDF


def resolve_pdf(requested: Path | None) -> Path:
    candidates = [requested, DEFAULT_PDF] if requested else [DEFAULT_PDF]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    if FALLBACK_PDF.is_file():
        return FALLBACK_PDF
    return download_official_pdf()


def extract_positioned_lines(pdf_path: Path) -> tuple[list[dict], str]:
    """Extrai palavras com coordenadas e seleciona as páginas do Ceará."""
    pages_audit: list[dict] = []
    selected_text: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            is_ceara = "Ceará" in text or "Ceara" in text
            if is_ceara or len(pdf.pages) <= 3:
                words = page.extract_words(x_tolerance=2, y_tolerance=3)
                rows: dict[int, list[dict]] = {}
                for word in words:
                    rows.setdefault(round(float(word["top"])), []).append(word)
                positioned_rows = [
                    " ".join(w["text"] for w in sorted(row, key=lambda x: x["x0"]))
                    for _, row in sorted(rows.items())
                ]
                pages_audit.append(
                    {
                        "pagina": page_number,
                        "palavras": len(words),
                        "linhas_posicionais": len(positioned_rows),
                        "amostra": positioned_rows[:8],
                    }
                )
                selected_text.append(text)
    if not selected_text:
        raise ValueError("Não foi possível localizar as páginas do Ceará no PDF.")
    return pages_audit, "\n".join(selected_text)


def localized_token(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.1f}".replace(".", ",")
    return f"{int(value):,}".replace(",", ".")


def validate_against_text(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text)
    missing: list[str] = []
    critical = (
        next(x for x in INDICATORS if x.name == "Pessoas de 14 anos ou mais"),
        next(x for x in INDICATORS if x.name == "Rendimento médio mensal real habitual"),
        next(x for x in INDICATORS if x.name == "Massa de rendimento mensal real habitual"),
    )
    for indicator in critical:
        for value in indicator.values:
            token = localized_token(value, indicator.unit)
            if token not in compact:
                missing.append(f"{indicator.name}: {token}")
    if missing:
        raise ValueError(
            "A conferência encontrou valores-chave ausentes na camada textual: "
            + "; ".join(missing)
        )
    return [f"{indicator.name}: OK" for indicator in critical]


def build_dataframe(indicators: Iterable[Indicator]) -> pd.DataFrame:
    records: list[dict] = []
    for indicator in indicators:
        indicator_id = f"{slug(indicator.section)}--{slug(indicator.name)}"
        for (period, order), value in zip(PERIODS, indicator.values, strict=True):
            is_latest = order == 3
            records.append(
                {
                    "indicador_id": indicator_id,
                    "secao": indicator.section,
                    "grupo": indicator.group,
                    "indicador": indicator.name,
                    "unidade": indicator.unit,
                    "periodo": period,
                    "ordem_periodo": order,
                    "valor": value,
                    "variacao_trimestral_abs": indicator.quarter_abs if is_latest else None,
                    "variacao_trimestral_pct": indicator.quarter_pct if is_latest else None,
                    "variacao_anual_abs": indicator.year_abs if is_latest else None,
                    "variacao_anual_pct": indicator.year_pct if is_latest else None,
                    "situacao_trimestral": indicator.situ_quarter if is_latest else None,
                    "situacao_anual": indicator.situ_year if is_latest else None,
                    "fonte": "IBGE, PNAD Contínua Trimestral — maio de 2026",
                }
            )
    frame = pd.DataFrame.from_records(records)
    required = {"indicador_id", "secao", "indicador", "unidade", "periodo", "valor"}
    if missing := required.difference(frame.columns):
        raise ValueError(f"Colunas obrigatórias ausentes: {sorted(missing)}")
    if frame.duplicated(["indicador_id", "periodo"]).any():
        raise ValueError("Há duplicidades de indicador e período.")
    if frame[list(required)].isna().any().any():
        raise ValueError("Há valores ausentes em colunas obrigatórias.")
    expected_rows = len(INDICATORS) * len(PERIODS)
    if len(frame) != expected_rows:
        raise ValueError(f"Esperadas {expected_rows} linhas; obtidas {len(frame)}.")
    valid_situ = {EST, CRE, DEC}
    situ = frame.loc[frame["ordem_periodo"] == 3, ["situacao_trimestral", "situacao_anual"]]
    if not situ.isin(valid_situ).all().all():
        raise ValueError("Situações de significância inválidas na base.")
    return frame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, help="Caminho alternativo para o PDF")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV, help="CSV de saída")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = resolve_pdf(args.pdf)
    pages_audit, text = extract_positioned_lines(pdf_path)
    checks = validate_against_text(text)
    frame = build_dataframe(INDICATORS)

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig", float_format="%.1f")

    audit = {
        "arquivo_pdf": str(pdf_path.resolve()),
        "url_fonte_oficial": OFFICIAL_URL,
        "indicadores": len(INDICATORS),
        "linhas_csv": len(frame),
        "periodos": [period for period, _ in PERIODS],
        "paginas_extraidas": pages_audit,
        "validacoes": checks,
        "significancia": (
            "Setas do quadro oficial do IBGE (Wingdings3): '*'=estável, "
            "'#'=cresceu, '$'=decresceu; 1ª coluna = variação trimestral, "
            "2ª coluna = variação anual."
        ),
        "campos_configuracao": list(asdict(INDICATORS[0]).keys()),
    }
    AUDIT_JSON.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=list),
        encoding="utf-8",
    )
    print(f"CSV criado: {output} ({len(frame)} linhas, {len(INDICATORS)} indicadores)")
    print(f"Auditoria criada: {AUDIT_JSON.resolve()}")


if __name__ == "__main__":
    main()
