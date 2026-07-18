"""Gera textos de análise das seções a partir dos CSVs (IA gratuita + fallback)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DETAIL_CSV = DATA_DIR / "pnad_ce_1tri2026.csv"
SERIES_CSV = DATA_DIR / "pnad_ce_serie.csv"
OUTPUT_JSON = DATA_DIR / "narratives.json"

SECTION_META = {
    "mercado": {
        "title": "Indicadores gerais do mercado de trabalho",
        "secao": "Mercado de trabalho",
        "indicadores": [
            "Taxa de desocupação",
            "Nível da ocupação",
            "Taxa de participação na força de trabalho",
        ],
    },
    "populacao": {
        "title": "População por condição de ocupação",
        "secao": "Mercado de trabalho",
        "indicadores": [
            "Ocupadas",
            "Desocupadas",
            "Fora da força de trabalho",
        ],
    },
    "ocupacao": {
        "title": "Ocupados por posição na ocupação",
        "secao": "Ocupação",
        "indicadores": None,  # todos da seção com variação
    },
    "atividades": {
        "title": "Ocupados por setor de atividade",
        "secao": "Atividades",
        "indicadores": None,
    },
    "rendimento": {
        "title": "Rendimento",
        "secao": "Rendimento",
        "indicadores": [
            "Rendimento médio mensal real habitual",
            "Massa de rendimento mensal real habitual",
        ],
    },
    "subutilizacao": {
        "title": "Subutilização da força de trabalho",
        "secao": "Subutilização",
        "indicadores": None,
    },
}

SIG_LABEL = {
    "cresceu": "alta significativa",
    "decresceu": "queda significativa",
    "estavel": "estável (dentro da margem de erro)",
}


def br(number: float, decimals: int = 1) -> str:
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "@").replace(".", ",").replace("@", ".")


def fmt_value(value: float, unit: str) -> str:
    if unit == "%":
        return f"{br(value)}%"
    if unit == "R$":
        return f"R$ {br(value, 0)}"
    if unit == "R$ milhões":
        return f"R$ {br(value * 1_000_000, 0)}"
    if unit == "Mil pessoas":
        return br(value * 1000, 0)
    return br(value, 0)


def fmt_delta(row: pd.Series, scope: str) -> str:
    unit = row["unidade"]
    situ = row.get(f"situacao_{scope}")
    if unit == "%":
        abs_v = row.get(f"variacao_{scope}_abs")
        if pd.isna(abs_v):
            return ""
        base = f"{'+' if abs_v >= 0 else ''}{br(float(abs_v))} p.p."
    else:
        pct = row.get(f"variacao_{scope}_pct")
        abs_v = row.get(f"variacao_{scope}_abs")
        if pd.isna(pct):
            return ""
        base = f"{'+' if pct >= 0 else ''}{br(float(pct))}%"
        if unit == "Mil pessoas" and not pd.isna(abs_v):
            base = f"{'+' if abs_v >= 0 else ''}{br(float(abs_v) * 1000, 0)} ({base})"
    if situ in SIG_LABEL:
        return f"{base}, {SIG_LABEL[situ]}"
    return base


def load_detail() -> pd.DataFrame:
    if not DETAIL_CSV.exists():
        raise FileNotFoundError(f"Base detalhada não encontrada: {DETAIL_CSV}")
    return pd.read_csv(DETAIL_CSV)


def latest_period(df: pd.DataFrame) -> str:
    return str(df.sort_values("ordem_periodo")["periodo"].iloc[-1])


def series_for(df: pd.DataFrame, indicator: str, section: str | None = None) -> pd.DataFrame:
    rows = df[df["indicador"] == indicator]
    if section:
        rows = rows[rows["secao"] == section]
    return rows.sort_values("ordem_periodo")


def facts_for_section(df: pd.DataFrame, key: str) -> dict:
    meta = SECTION_META[key]
    latest = latest_period(df)
    section_rows = df[df["secao"] == meta["secao"]]
    if meta["indicadores"]:
        section_rows = section_rows[section_rows["indicador"].isin(meta["indicadores"])]

    latest_rows = section_rows[section_rows["periodo"] == latest].copy()
    facts: list[dict] = []
    for _, row in latest_rows.iterrows():
        hist = series_for(df, row["indicador"], meta["secao"])
        values = [
            {"periodo": str(r["periodo"]), "valor": fmt_value(float(r["valor"]), str(r["unidade"]))}
            for _, r in hist.iterrows()
        ]
        facts.append(
            {
                "indicador": row["indicador"],
                "unidade": row["unidade"],
                "atual": fmt_value(float(row["valor"]), str(row["unidade"])),
                "serie": values,
                "variacao_trimestral": fmt_delta(row, "trimestral"),
                "variacao_anual": fmt_delta(row, "anual"),
                "situacao_trimestral": row.get("situacao_trimestral"),
                "situacao_anual": row.get("situacao_anual"),
            }
        )

    # Destaques: mudanças significativas
    highlights = [
        f
        for f in facts
        if f["situacao_trimestral"] in {"cresceu", "decresceu"}
        or f["situacao_anual"] in {"cresceu", "decresceu"}
    ]
    return {
        "titulo": meta["title"],
        "periodo": latest,
        "fatos": facts,
        "destaques": highlights[:12],
    }


def build_context(df: pd.DataFrame) -> dict:
    return {
        "periodo": latest_period(df),
        "secoes": {key: facts_for_section(df, key) for key in SECTION_META},
    }


def template_paragraph(section_key: str, block: dict) -> str:
    """Narrativa determinística a partir dos fatos (fallback sem IA)."""
    facts = block["fatos"]
    if not facts:
        return f"Sem dados suficientes para a seção {block['titulo']} no período {block['periodo']}."

    parts: list[str] = []
    periodo = block["periodo"]

    if section_key == "mercado":
        by_name = {f["indicador"]: f for f in facts}
        des = by_name.get("Taxa de desocupação")
        niv = by_name.get("Nível da ocupação")
        part = by_name.get("Taxa de participação na força de trabalho")
        if des and len(des["serie"]) >= 2:
            chain = " → ".join(v["valor"] for v in des["serie"])
            parts.append(
                f"A taxa de desocupação foi de {chain}. "
                f"No trimestre: **{des['variacao_trimestral'] or 'sem variação disponível'}**; "
                f"no ano: **{des['variacao_anual'] or 'sem variação disponível'}**."
            )
        if niv:
            parts.append(
                f"O nível da ocupação ficou em {niv['atual']} "
                f"(trimestre: {niv['variacao_trimestral'] or 'n/d'}; "
                f"ano: {niv['variacao_anual'] or 'n/d'})."
            )
        if part:
            parts.append(
                f"A participação na força de trabalho ficou em {part['atual']} "
                f"({part['variacao_trimestral'] or 'n/d'} no trimestre; "
                f"{part['variacao_anual'] or 'n/d'} no ano)."
            )
    else:
        # Prioriza destaques; senão os primeiros indicadores
        chosen = block["destaques"] or facts[:4]
        for item in chosen[:5]:
            serie = item["serie"]
            if len(serie) >= 2:
                before = serie[-2]["valor"]
                now = item["atual"]
                line = f"{item['indicador']}: de {before} para {now}"
            else:
                line = f"{item['indicador']}: {item['atual']}"
            bits = []
            if item["variacao_trimestral"]:
                bits.append(f"trimestre **{item['variacao_trimestral']}**")
            if item["variacao_anual"]:
                bits.append(f"ano **{item['variacao_anual']}**")
            if bits:
                line += " (" + "; ".join(bits) + ")"
            parts.append(line + ".")

    text = " ".join(parts)
    if not text.endswith("."):
        text += "."
    return f"{text} Período de referência: {periodo}."


def template_sections(context: dict) -> dict[str, str]:
    return {
        key: template_paragraph(key, block)
        for key, block in context["secoes"].items()
    }


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("Resposta da IA sem JSON.")
    return json.loads(text[start : end + 1])


def _prompt(context: dict) -> str:
    compact = {
        "periodo": context["periodo"],
        "secoes": {
            key: {
                "titulo": block["titulo"],
                "fatos": block["fatos"][:10],
            }
            for key, block in context["secoes"].items()
        },
    }
    return f"""Você é analista do mercado de trabalho do Ceará (PNAD Contínua/IBGE).
Escreva 6 parágrafos curtos em português do Brasil, um por seção.

Regras:
- Use SOMENTE os números e situações fornecidos nos fatos.
- Não invente comparações históricas (ex.: "desde 2012") nem causas não listadas.
- Destaque o principal achado de cada seção com **negrito** (markdown).
- Números já estão no padrão brasileiro; não reformate.
- Tom técnico, claro, 2 a 4 frases por seção.
- Responda APENAS um JSON com as chaves:
  mercado, populacao, ocupacao, atividades, rendimento, subutilizacao

Fatos:
{json.dumps(compact, ensure_ascii=False)}
"""


def call_groq(prompt: str) -> dict[str, str]:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY não configurada.")
    model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant").strip()
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": "Responda só JSON válido, sem markdown de fence.",
                },
                {"role": "user", "content": prompt},
            ],
        },
        timeout=90,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Groq HTTP {response.status_code}: {response.text[:300]}")
    content = response.json()["choices"][0]["message"]["content"]
    data = _extract_json_object(content)
    return {key: str(data[key]).strip() for key in SECTION_META if key in data}


def call_gemini(prompt: str) -> dict[str, str]:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY não configurada.")
    preferred = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
    models = [preferred]
    for candidate in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-latest"):
        if candidate not in models:
            models.append(candidate)

    last_error = ""
    for model in models:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={key}"
        )
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2},
            },
            timeout=90,
        )
        if response.status_code >= 400:
            last_error = f"Gemini HTTP {response.status_code} ({model}): {response.text[:300]}"
            continue
        payload = response.json()
        content = payload["candidates"][0]["content"]["parts"][0]["text"]
        data = _extract_json_object(content)
        return {key: str(data[key]).strip() for key in SECTION_META if key in data}
    raise RuntimeError(last_error or "Gemini sem resposta válida.")


def generate_sections(df: pd.DataFrame | None = None) -> tuple[dict[str, str], str]:
    """Retorna (seções, fonte). Fonte: groq | gemini | template."""
    frame = df if df is not None else load_detail()
    context = build_context(frame)
    prompt = _prompt(context)
    errors: list[str] = []

    # Gemini primeiro (chave mais comum neste projeto); depois Groq.
    if os.environ.get("GEMINI_API_KEY", "").strip():
        try:
            sections = call_gemini(prompt)
            if len(sections) >= 4:
                fallback = template_sections(context)
                for key in SECTION_META:
                    sections.setdefault(key, fallback[key])
                return sections, "gemini"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"gemini: {exc}")

    if os.environ.get("GROQ_API_KEY", "").strip():
        try:
            sections = call_groq(prompt)
            if len(sections) >= 4:
                fallback = template_sections(context)
                for key in SECTION_META:
                    sections.setdefault(key, fallback[key])
                return sections, "groq"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"groq: {exc}")

    sections = template_sections(context)
    if errors:
        print("Narrativas IA falharam; usando template:", "; ".join(errors))
    return {k: sections[k] for k in SECTION_META}, "template"


def ai_keys_configured() -> bool:
    return bool(
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GROQ_API_KEY", "").strip()
    )


def ensure_ai_narratives(*, force: bool = False) -> dict:
    """Regenera narrativas com IA se houver chave e a fonte ainda não for IA."""
    current = {}
    if OUTPUT_JSON.exists():
        try:
            current = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            current = {}
    source = str(current.get("source", "")).lower()
    if not force and source in {"groq", "gemini"}:
        return current
    if not ai_keys_configured():
        return current if current else load_narratives()
    generate_and_save()
    return load_narratives()


def save_narratives(sections: dict[str, str], source: str, periodo: str) -> Path:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "periodo": periodo,
        "source": source,
        "sections": {key: sections[key] for key in SECTION_META},
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return OUTPUT_JSON


def generate_and_save(df: pd.DataFrame | None = None) -> dict:
    frame = df if df is not None else load_detail()
    sections, source = generate_sections(frame)
    path = save_narratives(sections, source, latest_period(frame))
    return {
        "path": str(path),
        "source": source,
        "periodo": latest_period(frame),
        "sections": list(SECTION_META.keys()),
    }


def load_narratives() -> dict:
    if OUTPUT_JSON.exists():
        return json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
    result = generate_and_save()
    return json.loads(Path(result["path"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    info = generate_and_save()
    print(json.dumps(info, ensure_ascii=False, indent=2))
