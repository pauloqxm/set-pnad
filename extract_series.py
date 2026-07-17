"""Extrai série temporal do Ceará a partir dos quadros sintéticos em pnad/.

Cada arquivo pnadc_YYYYQQ_trimestre_quadroSintetico.pdf contribui com o valor
do trimestre de referência (3ª coluna das estimativas). O dashboard usa o
trimestre mais recente e os três anteriores.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd
import pdfplumber

BASE_DIR = Path(__file__).resolve().parent
PNAD_DIR = BASE_DIR / "pnad"
OUTPUT_CSV = BASE_DIR / "data" / "pnad_ce_serie.csv"
AUDIT_JSON = BASE_DIR / "data" / "series_extraction_audit.json"

QUARTER_LABEL = {
    1: "jan-fev-mar",
    2: "abr-mai-jun",
    3: "jul-ago-set",
    4: "out-nov-dez",
}

INDICATORS = (
    ("Taxa de desocupação", "%", r"Taxa de desocupação\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", "main"),
    ("Nível da ocupação", "%", r"Nível da ocupação\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", "main"),
    (
        "Taxa de participação na força de trabalho",
        "%",
        r"Taxa de participação na força de trabalho\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
        "main",
    ),
    ("Pessoas de 14 anos ou mais", "Mil pessoas", r"\bTotal\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", "main"),
    ("Na força de trabalho", "Mil pessoas", r"Na força de trabalho\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", "main"),
    ("Ocupadas", "Mil pessoas", r"\bOcupada[s]?\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", "main"),
    ("Desocupadas", "Mil pessoas", r"\bDesocupada[s]?\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", "main"),
    ("Fora da força de trabalho", "Mil pessoas", r"Fora da força de trabalho\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", "main"),
    ("Empregados", "Mil pessoas", r"\bEmpregado[s]?\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", "main"),
    (
        "Setor privado — com carteira",
        "Mil pessoas",
        r"Com carteira\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
        "main_first",
    ),
    ("Setor público", "Mil pessoas", r"Setor público\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", "main"),
    ("Trabalhadores por conta própria", "Mil pessoas", r"Conta própria\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", "main"),
    (
        "Taxa composta de subutilização da força de trabalho",
        "%",
        r"Taxa composta de subutilização da força de trabalho\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
        "sub",
    ),
    (
        "Percentual de pessoas desalentadas",
        "%",
        r"Percentual de pessoas desalentadas.*?\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
        "sub",
    ),
)


def parse_num(value: str) -> float:
    value = value.strip()
    if "," in value:
        return float(value.replace(".", "").replace(",", "."))
    return float(value.replace(".", ""))


def period_from_code(code: str) -> tuple[str, int, int, int]:
    """Converte YYYYQQ (ex.: 202601) em rótulo e chave de ordenação."""
    year = int(code[:4])
    quarter = int(code[4:6])
    if quarter not in QUARTER_LABEL:
        raise ValueError(f"Código de trimestre inválido: {code}")
    label = f"{QUARTER_LABEL[quarter]}/{year}"
    order = year * 10 + quarter
    return label, year, quarter, order


def list_quadro_pdfs(folder: Path) -> list[tuple[Path, str, str, int]]:
    files = []
    for path in sorted(folder.glob("pnadc_*_trimestre_quadroSintetico.pdf")):
        match = re.search(r"pnadc_(\d{6})_trimestre", path.name)
        if not match:
            continue
        code = match.group(1)
        label, year, quarter, order = period_from_code(code)
        files.append((path, code, label, order))
    files.sort(key=lambda item: item[3])
    return files


def extract_ceara_pages(pdf_path: Path) -> tuple[str, str, str]:
    """Localiza as páginas do Ceará sem varrer o PDF inteiro página a página."""
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        # Nos quadros sintéticos, Ceará costuma ficar perto da página 31.
        preferred = [i for i in range(28, min(36, total))]
        remaining = [i for i in range(total) if i not in preferred]
        page_order = preferred + remaining

        for index in page_order:
            page = pdf.pages[index]
            text = page.extract_text() or ""
            if "Indicadores de subutilização" in text:
                continue
            if "Taxa de desocupação" not in text:
                continue
            if not re.search(r"Divulgação:\s+\S+\s+de\s+\d{4}\s+Ceará\b", text):
                continue
            period_match = re.search(r"Trimestre móvel:\s*([^\n]+)", text)
            period = period_match.group(1).strip() if period_match else ""
            sub_text = ""
            if index + 1 < total:
                sub_text = pdf.pages[index + 1].extract_text() or ""
            return text, sub_text, period
    raise ValueError(f"Página do Ceará não encontrada em {pdf_path.name}")


def extract_value(text: str, pattern: str, mode: str = "main") -> float | None:
    matches = list(re.finditer(pattern, text, flags=re.S))
    if not matches:
        return None
    match = matches[0] if mode in {"main", "main_first", "sub"} else matches[-1]
    return parse_num(match.group(3))


def extract_rendimento(text: str) -> tuple[float | None, float | None]:
    totals = re.findall(r"Total\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", text)
    if len(totals) < 2:
        return None, None
    return parse_num(totals[-2][2]), parse_num(totals[-1][2])


def extract_quarter(pdf_path: Path, code: str, label: str, order: int) -> list[dict]:
    main_text, sub_text, header_period = extract_ceara_pages(pdf_path)
    if header_period and header_period != label:
        # Prefere o período declarado no PDF quando divergir do nome do arquivo.
        label = header_period

    records: list[dict] = []
    for name, unit, pattern, mode in INDICATORS:
        source = sub_text if mode == "sub" else main_text
        value = extract_value(source, pattern, mode)
        if value is None:
            continue
        records.append(
            {
                "codigo_trimestre": code,
                "periodo": label,
                "ordem_periodo": order,
                "indicador": name,
                "unidade": unit,
                "valor": value,
                "arquivo_pdf": pdf_path.name,
                "fonte": "IBGE, PNAD Contínua Trimestral — quadro sintético",
            }
        )

    medio, massa = extract_rendimento(main_text)
    if medio is not None:
        records.append(
            {
                "codigo_trimestre": code,
                "periodo": label,
                "ordem_periodo": order,
                "indicador": "Rendimento médio mensal real habitual",
                "unidade": "R$",
                "valor": medio,
                "arquivo_pdf": pdf_path.name,
                "fonte": "IBGE, PNAD Contínua Trimestral — quadro sintético",
            }
        )
    if massa is not None:
        records.append(
            {
                "codigo_trimestre": code,
                "periodo": label,
                "ordem_periodo": order,
                "indicador": "Massa de rendimento mensal real habitual",
                "unidade": "R$ milhões",
                "valor": massa,
                "arquivo_pdf": pdf_path.name,
                "fonte": "IBGE, PNAD Contínua Trimestral — quadro sintético",
            }
        )
    return records


def build_series(folder: Path, last_n: int = 4) -> tuple[pd.DataFrame, dict]:
    pdfs = list_quadro_pdfs(folder)
    if not pdfs:
        raise FileNotFoundError(
            f"Nenhum quadro sintético encontrado em {folder}. "
            "Espere arquivos pnadc_YYYYQQ_trimestre_quadroSintetico.pdf"
        )

    selected = pdfs[-last_n:] if last_n else pdfs
    records: list[dict] = []
    for path, code, label, order in selected:
        print(f"  - Lendo {path.name} ({label})...", flush=True)
        quarter_rows = extract_quarter(path, code, label, order)
        print(f"    OK ({len(quarter_rows)} indicadores)", flush=True)
        records.extend(quarter_rows)

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        raise ValueError("Nenhum indicador foi extraído dos PDFs.")
    if frame.duplicated(["periodo", "indicador"]).any():
        raise ValueError("Há duplicidades de período e indicador na série.")

    audit = {
        "pasta": str(folder.resolve()),
        "arquivos_disponiveis": [path.name for path, *_ in pdfs],
        "arquivos_usados": [path.name for path, *_ in selected],
        "periodos": frame["periodo"].drop_duplicates().tolist(),
        "indicadores": sorted(frame["indicador"].unique().tolist()),
        "linhas_csv": len(frame),
        "trimestre_atual": selected[-1][2],
        "tres_anteriores": [item[2] for item in selected[:-1]],
    }
    return frame, audit


def csv_is_up_to_date(output: Path, folder: Path, last_n: int) -> bool:
    """True se o CSV já cobre exatamente os PDFs mais recentes de pnad/."""
    if not output.exists():
        return False
    pdfs = list_quadro_pdfs(folder)
    if not pdfs:
        return False
    selected_names = {path.name for path, *_ in (pdfs[-last_n:] if last_n else pdfs)}
    try:
        existing = pd.read_csv(output, usecols=["arquivo_pdf"])
    except (ValueError, pd.errors.ParserError, OSError):
        return False
    return set(existing["arquivo_pdf"].unique()) == selected_names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pasta", type=Path, default=PNAD_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV)
    parser.add_argument(
        "--last-n",
        type=int,
        default=4,
        help="Quantidade de trimestres mais recentes (atual + anteriores).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reextrai dos PDFs mesmo que o CSV já esteja atualizado.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.force and csv_is_up_to_date(args.output, args.pasta, args.last_n):
        print(
            f"Série já está atualizada com os PDFs de {args.pasta.name}\\ — nada a fazer. "
            "Use --force para reextrair."
        )
        return
    print("Detectado trimestre novo (ou CSV ausente). Extraindo dos PDFs...", flush=True)
    frame, audit = build_series(args.pasta, last_n=args.last_n)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, encoding="utf-8-sig", float_format="%.1f")
    AUDIT_JSON.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Série criada: {args.output} ({len(frame)} linhas, "
        f"{frame['periodo'].nunique()} trimestres, {frame['indicador'].nunique()} indicadores)"
    )
    print("Períodos:", " | ".join(audit["periodos"]))


if __name__ == "__main__":
    main()
