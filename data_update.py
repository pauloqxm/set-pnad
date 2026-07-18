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
DEFAULT_GITHUB_REPO = "pauloqxm/set-pnad"

PDF_NAME_RE = re.compile(
    r"^pnadc_\d{6}_trimestre_quadroSintetico\.pdf$",
    re.IGNORECASE,
)

CSV_PATHS = (
    DATA_DIR / "pnad_ce_serie.csv",
    DATA_DIR / "pnad_comparativo_1tri2026.csv",
    DATA_DIR / "series_extraction_audit.json",
    DATA_DIR / "regional_extraction_audit.json",
    DATA_DIR / "narratives.json",
    DATA_DIR / "glossary.json",
)


def upload_enabled() -> bool:
    return bool(os.environ.get("ADMIN_UPLOAD_TOKEN", "").strip())


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    # Railway às vezes cola o valor com aspas.
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        token = token[1:-1].strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if token.lower().startswith("token "):
        token = token[6:].strip()
    return token


def github_configured() -> bool:
    return bool(_github_token())


def github_repo() -> str:
    return os.environ.get("GITHUB_REPO", DEFAULT_GITHUB_REPO).strip() or DEFAULT_GITHUB_REPO


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


def quarter_code_from_name(filename: str) -> str:
    match = re.search(r"pnadc_(\d{6})_trimestre", Path(filename).name, re.I)
    if not match:
        raise ValueError(f"Não foi possível ler o código YYYYQQ de {filename}.")
    return match.group(1)


def latest_known_quarter_code() -> str | None:
    codes: list[str] = []
    for path, code, *_ in extract_series.list_quadro_pdfs(PNAD_DIR):
        codes.append(code)
    series_csv = DATA_DIR / "pnad_ce_serie.csv"
    if series_csv.exists():
        try:
            import pandas as pd

            frame = pd.read_csv(series_csv, usecols=["codigo_trimestre"])
            codes.extend(
                str(code).zfill(6)
                for code in frame["codigo_trimestre"].dropna().unique().tolist()
            )
        except Exception:
            pass
    return max(codes) if codes else None


def ensure_upload_is_current_or_newer(filename: str) -> None:
    """Impede PDF antigo de virar o 'trimestre atual' e corromper a série."""
    uploaded = quarter_code_from_name(filename)
    current = latest_known_quarter_code()
    if current and uploaded < current:
        label_up = extract_series.period_from_code(uploaded)[0]
        label_cur = extract_series.period_from_code(current)[0]
        raise ValueError(
            f"O PDF enviado é mais antigo que a série atual. "
            f"Enviado: {filename} ({label_up}). "
            f"Atual na base: pnadc_{current}_... ({label_cur}). "
            "Envie apenas o quadro sintético do trimestre mais recente do IBGE."
        )


def regenerate_csvs(*, force_series: bool = True) -> dict:
    """Regenera série temporal e comparativo regional a partir de pnad/."""
    PNAD_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    synced = sync_pnad_pdfs_from_github()

    pdfs = extract_series.list_quadro_pdfs(PNAD_DIR)
    if len(pdfs) < 2:
        raise RuntimeError(
            "Poucos PDFs em pnad/ para montar a série. "
            "No Railway a pasta começa vazia: configure GITHUB_TOKEN para "
            "baixar os PDFs do repositório antes da regeneração, ou faça "
            "upload dos 4 trimestres mais recentes."
        )

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
        "pdfs_baixados_github": synced,
        "force_series": force_series,
    }


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "set-pnad-dashboard",
    }


def _format_github_http_error(response: requests.Response, *, context: str) -> str:
    status = response.status_code
    body = (response.text or "")[:300]
    if status == 401:
        return (
            f"{context}: 401 Unauthorized. O GITHUB_TOKEN é inválido, expirou "
            "ou foi colado com espaços/aspas. Crie um novo PAT em "
            "GitHub → Settings → Developer settings → Personal access tokens "
            "com Contents: Read and write no repositório "
            f"{github_repo()}, atualize a variável no Railway e faça redeploy."
        )
    if status == 403:
        return (
            f"{context}: 403 Forbidden. O token não tem permissão de escrita "
            f"em {github_repo()}. No PAT fine-grained: Repository access = "
            "este repo e Contents = Read and write. No classic: escopo `repo`."
        )
    if status == 404:
        return (
            f"{context}: 404 Not Found. Confira GITHUB_REPO "
            f"(atual: {github_repo()}) e se o token enxerga esse repositório."
        )
    return f"{context}: HTTP {status} — {body}"


def verify_github_access() -> None:
    token = _github_token()
    if not token:
        raise RuntimeError(
            "GitHub não configurado. Defina GITHUB_TOKEN no Railway "
            f"(repositório padrão: {DEFAULT_GITHUB_REPO})."
        )
    repo = github_repo()
    response = requests.get(
        f"https://api.github.com/repos/{repo}",
        headers=_github_headers(token),
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            _format_github_http_error(response, context="Falha ao validar acesso ao GitHub")
        )
    perms = (response.json() or {}).get("permissions") or {}
    if perms and not perms.get("push", False):
        raise RuntimeError(
            f"O token acessa {repo}, mas sem permissão de push (Contents: Write). "
            "Ajuste o PAT e tente de novo."
        )


def sync_pnad_pdfs_from_github() -> list[str]:
    """Baixa PDFs de pnad/ do GitHub para completar a série no container."""
    token = _github_token()
    if not token:
        return []
    repo = github_repo()
    branch = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"
    response = requests.get(
        f"https://api.github.com/repos/{repo}/contents/pnad",
        headers=_github_headers(token),
        params={"ref": branch},
        timeout=60,
    )
    if response.status_code == 404:
        return []
    if response.status_code >= 400:
        raise RuntimeError(
            _format_github_http_error(response, context="Falha ao listar pnad/ no GitHub")
        )

    PNAD_DIR.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    for item in response.json():
        name = item.get("name") or ""
        if not PDF_NAME_RE.match(name):
            continue
        target = PNAD_DIR / name
        if target.exists() and target.stat().st_size > 0:
            continue
        download_url = item.get("download_url")
        if not download_url:
            continue
        file_response = requests.get(download_url, timeout=180)
        file_response.raise_for_status()
        target.write_bytes(file_response.content)
        downloaded.append(name)
    return downloaded


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
    if response.status_code >= 400:
        raise RuntimeError(
            _format_github_http_error(response, context=f"Falha ao ler {path} no GitHub")
        )
    return response.json()


def push_file_to_github(
    *,
    local_path: Path,
    repo_path: str,
    message: str,
) -> str:
    token = _github_token()
    repo = github_repo()
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
            _format_github_http_error(response, context=f"Falha ao enviar {repo_path}")
        )
    return repo_path


def push_updates_to_github(pdf_path: Path | None = None) -> list[str]:
    verify_github_access()

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

    # Completa pnad/ com os PDFs do GitHub antes de validar antiguidade.
    sync_pnad_pdfs_from_github()
    ensure_upload_is_current_or_newer(filename)

    raw = decode_upload(contents)
    pdf_path = save_pdf(filename, raw)
    stats = regenerate_csvs(force_series=True)

    narrative_info: dict = {}
    glossary_info: dict = {}
    try:
        import generate_narratives

        narrative_info = generate_narratives.generate_and_save()
        glossary_info = generate_narratives.generate_glossary_and_save()
        stats["narratives"] = narrative_info
        stats["glossary"] = glossary_info
    except Exception as exc:  # noqa: BLE001
        narrative_info = {"error": str(exc)}
        glossary_info = {"error": str(exc)}
        stats["narratives"] = narrative_info
        stats["glossary"] = glossary_info

    result = {
        "pdf": pdf_path.name,
        "stats": stats,
        "github": None,
        "narratives": narrative_info,
        "glossary": glossary_info,
        "aviso": (
            "Série temporal, comparativo regional, textos de análise e glossário "
            "foram atualizados. A base detalhada do Ceará (setas de significância) continua "
            "sendo a última versão curada em data/pnad_ce_1tri2026.csv."
        ),
    }

    source = narrative_info.get("source")
    gloss_source = glossary_info.get("source")
    if source == "template" or gloss_source == "template":
        result["aviso"] += (
            " Parte dos textos usou o gerador automático (template), porque "
            "GROQ_API_KEY/GEMINI_API_KEY não estavam disponíveis ou a IA falhou."
        )
    elif source in {"groq", "gemini"} or gloss_source in {"groq", "gemini"}:
        used = gloss_source or source
        result["aviso"] += f" Textos gerados por IA ({used})."

    if push_github:
        if not github_configured():
            result["github"] = {"skipped": True, "motivo": "nao_configurado"}
            result["aviso"] += (
                " Os dados foram atualizados só neste servidor (Railway). "
                "Para aparecer no GitHub, configure GITHUB_TOKEN no Railway "
                f"e reenvie o PDF (repo: {DEFAULT_GITHUB_REPO})."
            )
        else:
            result["github"] = {
                "arquivos": push_updates_to_github(pdf_path),
                "repo": github_repo(),
                "branch": os.environ.get("GITHUB_BRANCH", "main"),
            }
            result["aviso"] += (
                " Arquivos enviados ao GitHub; se o Railway estiver conectado ao "
                "repositório, um novo deploy deve ocorrer em seguida."
            )
    elif not github_configured():
        result["github"] = {"skipped": True, "motivo": "nao_configurado"}
        result["aviso"] += (
            f" Nada foi enviado ao GitHub ({DEFAULT_GITHUB_REPO}). "
            "Configure GITHUB_TOKEN no Railway para publicar automaticamente."
        )
    return result
