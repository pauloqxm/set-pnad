"""Pipeline de atualização: salva PDF, regenera CSVs e envia ao GitHub."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from pathlib import Path

import requests

import extract_regional
import extract_series

BASE_DIR = Path(__file__).resolve().parent
PNAD_DIR = BASE_DIR / "pnad"
DATA_DIR = BASE_DIR / "data"

PDF_NAME_RE = re.compile(
    r"^pnadc_\d{6}_trimestre_quadroSintetico\.pdf$",
    re.IGNORECASE,
)

CSV_PATHS = (
    DATA_DIR / "pnad_ce_serie.csv",
    DATA_DIR / "pnad_comparativo_1tri2026.csv",
    DATA_DIR / "series_extraction_audit.json",
    DATA_DIR / "regional_extraction_audit.json",
)


def upload_enabled() -> bool:
    return bool(os.environ.get("ADMIN_UPLOAD_TOKEN", "").strip())


def github_configured() -> bool:
    return bool(
        os.environ.get("GITHUB_TOKEN", "").strip()
        and os.environ.get("GITHUB_REPO", "").strip()
    )


def validate_token(token: str | None) -> bool:
    expected = os.environ.get("ADMIN_UPLOAD_TOKEN", "").strip()
    if not expected:
        return False
    return (token or "").strip() == expected


def decode_upload(contents: str) -> bytes:
    if "," not in contents:
        raise ValueError("Conteúdo de upload inválido.")
    _, encoded = contents.split(",", 1)
    try:
        return base64.b64decode(encoded)
    except binascii.Error as exc:
        raise ValueError("Não foi possível decodificar o PDF enviado.") from exc


def save_pdf(filename: str, raw: bytes) -> Path:
    name = Path(filename).name
    if not PDF_NAME_RE.match(name):
        raise ValueError(
            "Nome inválido. Use o padrão IBGE: "
            "pnadc_YYYYQQ_trimestre_quadroSintetico.pdf "
            "(ex.: pnadc_202601_trimestre_quadroSintetico.pdf)."
        )
    if not raw.startswith(b"%PDF"):
        raise ValueError("O arquivo enviado não parece ser um PDF válido.")
    PNAD_DIR.mkdir(parents=True, exist_ok=True)
    path = PNAD_DIR / name
    path.write_bytes(raw)
    return path


def regenerate_csvs(*, force_series: bool = True) -> dict:
    """Regenera série temporal e comparativo regional a partir de pnad/."""
    PNAD_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    series_frame, series_audit = extract_series.build_series(PNAD_DIR, last_n=4)
    extract_series.OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    series_frame.to_csv(
        extract_series.OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig",
        float_format="%.1f",
    )
    extract_series.AUDIT_JSON.write_text(
        json.dumps(series_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    pdf_path = extract_regional.resolve_pdf(None)
    regional_frame, regional_audit = extract_regional.build_dataframe(pdf_path)
    extract_regional.OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    regional_frame.to_csv(
        extract_regional.OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig",
        float_format="%.1f",
    )
    extract_regional.AUDIT_JSON.write_text(
        json.dumps(regional_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "serie_periodos": series_audit.get("periodos", []),
        "serie_linhas": len(series_frame),
        "comparativo_periodo": regional_audit.get("periodo"),
        "comparativo_linhas": len(regional_frame),
        "pdf_usado_comparativo": pdf_path.name,
        "force_series": force_series,
    }


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_get_file(repo: str, path: str, branch: str, token: str) -> dict | None:
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    response = requests.get(
        url,
        headers=_github_headers(token),
        params={"ref": branch},
        timeout=60,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def push_file_to_github(
    *,
    local_path: Path,
    repo_path: str,
    message: str,
) -> str:
    token = os.environ["GITHUB_TOKEN"].strip()
    repo = os.environ["GITHUB_REPO"].strip()
    branch = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"

    existing = _github_get_file(repo, repo_path, branch, token)
    payload = {
        "message": message,
        "content": base64.b64encode(local_path.read_bytes()).decode("ascii"),
        "branch": branch,
    }
    if existing and "sha" in existing:
        payload["sha"] = existing["sha"]

    url = f"https://api.github.com/repos/{repo}/contents/{repo_path}"
    response = requests.put(
        url,
        headers=_github_headers(token),
        json=payload,
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Falha ao enviar {repo_path} ao GitHub "
            f"({response.status_code}): {response.text[:400]}"
        )
    return repo_path


def push_updates_to_github(pdf_path: Path | None = None) -> list[str]:
    if not github_configured():
        raise RuntimeError(
            "GitHub não configurado. Defina GITHUB_TOKEN e GITHUB_REPO."
        )

    pushed: list[str] = []
    for path in CSV_PATHS:
        if not path.exists():
            continue
        repo_path = path.relative_to(BASE_DIR).as_posix()
        pushed.append(
            push_file_to_github(
                local_path=path,
                repo_path=repo_path,
                message=f"chore(data): atualiza {path.name} via upload PNAD",
            )
        )

    push_pdfs = os.environ.get("GITHUB_PUSH_PDFS", "1").strip() != "0"
    if push_pdfs and pdf_path and pdf_path.exists():
        repo_path = pdf_path.relative_to(BASE_DIR).as_posix()
        pushed.append(
            push_file_to_github(
                local_path=pdf_path,
                repo_path=repo_path,
                message=f"chore(data): adiciona {pdf_path.name}",
            )
        )
    return pushed


def process_upload(
    *,
    contents: str,
    filename: str,
    token: str | None,
    push_github: bool,
) -> dict:
    if not validate_token(token):
        raise PermissionError("Token de administração inválido.")

    raw = decode_upload(contents)
    pdf_path = save_pdf(filename, raw)
    stats = regenerate_csvs(force_series=True)

    result = {
        "pdf": pdf_path.name,
        "stats": stats,
        "github": None,
        "aviso": (
            "Série temporal e comparativo regional foram atualizados. "
            "A base detalhada do Ceará (setas de significância) continua "
            "sendo a última versão curada em data/pnad_ce_1tri2026.csv."
        ),
    }

    if push_github:
        if not github_configured():
            result["github"] = {"skipped": True, "motivo": "nao_configurado"}
            result["aviso"] += (
                " Envio ao GitHub foi solicitado, mas GITHUB_TOKEN e GITHUB_REPO "
                "não estão definidos — os CSVs foram atualizados só neste servidor. "
                "No Railway, configure essas variáveis para publicar no repositório."
            )
        else:
            result["github"] = {
                "arquivos": push_updates_to_github(pdf_path),
                "repo": os.environ.get("GITHUB_REPO", ""),
                "branch": os.environ.get("GITHUB_BRANCH", "main"),
            }
            result["aviso"] += (
                " Arquivos enviados ao GitHub; se o Railway estiver conectado ao "
                "repositório, um novo deploy deve ocorrer em seguida."
            )
    return result
