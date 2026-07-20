# Deploy — Dashboard PNAD Ceará

Aplicação **Dash + Gunicorn** com painel da PNAD Contínua (Ceará e comparativo
regional). Em produção o app lê CSVs em `data/`. Há também uma aba **Atualizar
dados** para upload do PDF do IBGE, regeneração automática dos CSVs e push
opcional ao GitHub (dispara novo deploy no Railway).

## Estrutura relevante para o deploy

```
analise_pnad/
├── Dockerfile
├── DEPLOY.md
├── requirements.txt
├── app.py
├── data_update.py
├── extract_series.py
├── extract_regional.py
├── extract_capitals_rm.py
├── assets/
│   └── style.css
└── data/
    ├── pnad_ce_1tri2026.csv
    ├── pnad_ce_serie.csv
    ├── pnad_comparativo_1tri2026.csv
    └── pnad_capitais_rm_nordeste.csv
```

## Fonte de dados

| Arquivo | Uso no dashboard | Atualização por upload |
|---------|------------------|------------------------|
| `data/pnad_ce_serie.csv` | Série (atual + 3 trimestres) | Sim |
| `data/pnad_comparativo_1tri2026.csv` | Comparativo regional | Sim |
| `data/pnad_capitais_rm_nordeste.csv` | Capitais e RMs do Nordeste | Sim |
| `data/pnad_capitais_rm_serie.csv` | Série Fortaleza / RM Fortaleza | Sim |
| `data/pnad_ce_1tri2026.csv` | Análise detalhada + setas IBGE | Não (base curada) |

## Pré-requisitos

- Conta no [GitHub](https://github.com)
- Conta no [Railway](https://railway.app)
- Git instalado
- (Opcional) Personal Access Token do GitHub com permissão `contents:write`

## Passo 1: Repositório GitHub

```bash
cd analise_pnad

git init
git add Dockerfile DEPLOY.md requirements.txt app.py data_update.py \
  extract_series.py extract_regional.py extract_capitals_rm.py assets data \
  .dockerignore .gitignore README.md
git commit -m "Deploy: dashboard PNAD Ceará"
git branch -M main
git remote add origin https://github.com/pauloqxm/set-pnad.git
git push -u origin main
```

Repositório: https://github.com/pauloqxm/set-pnad

Confirme que os três CSVs de `data/` estão no commit.

## Passo 2: Deploy no Railway

### Dashboard

1. Acesse https://railway.app e faça login com GitHub
2. **New Project** → **Deploy from GitHub repo**
3. Selecione o repositório
4. Railway detecta o `Dockerfile` e faz o build
5. Em **Settings** → **Networking** → **Generate Domain**
6. Em **Variables**, configure (recomendado):

| Variável | Exemplo | Descrição |
|----------|---------|-----------|
| `ADMIN_UPLOAD_TOKEN` | `uma-senha-forte` | Libera a aba Atualizar dados |
| `GITHUB_TOKEN` | `ghp_...` | PAT com escrita no repositório |
| `GITHUB_REPO` | `pauloqxm/set-pnad` | Opcional (já é o padrão) |
| `GITHUB_BRANCH` | `main` | Branch (padrão `main`) |
| `GITHUB_PUSH_PDFS` | `1` | `0` para não versionar o PDF |

### CLI

```bash
npm i -g @railway/cli
railway login
railway init
railway up
```

## Passo 3: Verificar

| URL | Esperado |
|-----|----------|
| `/` | Dashboard (abas Análise, Comparativo e Atualizar dados) |

## Upload automático (PDF → CSV → GitHub)

1. Abra a aba **Atualizar dados**
2. Informe o `ADMIN_UPLOAD_TOKEN`
3. Envie `pnadc_YYYYQQ_trimestre_quadroSintetico.pdf`
4. Marque **Enviar CSV (e PDF) automaticamente para o GitHub**
5. Clique em **Processar upload**

Fluxo:

1. PDF salvo em `pnad/` no container
2. Regenera `pnad_ce_serie.csv` e `pnad_comparativo_1tri2026.csv`
3. Regenera `data/narratives.json` (textos das seções 1–6)
4. Envia os arquivos ao GitHub via API
5. O Railway redesplega a partir do repositório

**Narrativas automáticas:** no upload, o sistema gera os textos azuis das
seções com IA gratuita (Groq; opcionalmente Gemini). Se não houver chave de
API, usa um gerador determinístico a partir dos números da base detalhada.

**Importante:** a base detalhada do Ceará com setas de significância
(`pnad_ce_1tri2026.csv`) não é reescrita pelo upload do PDF sintético.

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `PORT` | `8051` | Porta (Railway define em produção) |
| `DASH_DEBUG` | `0` | `1` só em desenvolvimento local |
| `HOST` | `0.0.0.0` em produção | Bind no modo `python app.py` |
| `USUARIO` | — | Usuário do login do painel |
| `SENHA` | — | Senha do login do painel |
| `SECRET_KEY` | — | Chave da sessão Flask (opcional) |
| `ADMIN_UPLOAD_TOKEN` | — | Libera a aba Atualizar dados |
| `GITHUB_TOKEN` | — | PAT com escrita no repositório |
| `GITHUB_REPO` | `pauloqxm/set-pnad` | Repositório alvo do push |
| `GITHUB_BRANCH` | `main` | Branch |
| `GITHUB_PUSH_PDFS` | `1` | `0` para não versionar o PDF |
| `GROQ_API_KEY` | — | Chave gratuita em https://console.groq.com |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Modelo Groq |
| `GEMINI_API_KEY` | — | Opcional (fallback) https://aistudio.google.com/apikey |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Modelo Gemini |

## Build local

```bash
docker build -t pnad-ceara .
docker run -p 8051:8051 -e PORT=8051 \
  -e USUARIO=admin \
  -e SENHA=segredo \
  -e ADMIN_UPLOAD_TOKEN=segredo \
  pnad-ceara
```

- http://localhost:8051/

## Desenvolvimento local (Windows)

```bat
executar_dashboard.bat
```

Para testar upload local:

```powershell
$env:DASH_DEBUG="1"
$env:USUARIO="admin"
$env:SENHA="segredo"
$env:ADMIN_UPLOAD_TOKEN="segredo"
python app.py
```

## Atualizações

- `git push` na branch conectada dispara novo deploy
- Ou use a aba **Atualizar dados** (com token + GitHub configurados)
- Novo trimestre detalhado com setas: atualize `extract_data.py` / CSV curado e faça push

## Troubleshooting

### Upload recusado

- Confira `ADMIN_UPLOAD_TOKEN` no Railway e no formulário
- Nome do arquivo deve ser `pnadc_YYYYQQ_trimestre_quadroSintetico.pdf`

### GitHub falhou

- **401 Unauthorized:** token inválido/expirado ou colado com aspas. Gere um novo PAT
- **403 Forbidden:** falta permissão de escrita no repositório
- Token fine-grained recomendado:
  1. GitHub → Settings → Developer settings → [Personal access tokens](https://github.com/settings/tokens)
  2. **Generate new token (fine-grained)**
  3. Resource owner: sua conta
  4. Repository access: **Only select repositories** → `set-pnad`
  5. Permissions → Repository → **Contents: Read and write**
  6. Generate e copie o valor (`github_pat_...`)
  7. Railway → Variables → `GITHUB_TOKEN` = cole **sem aspas**
  8. Redeploy e reenvie o PDF
- Classic token: use escopo `repo`
- `GITHUB_REPO` no formato `dono/nome` (padrão: `pauloqxm/set-pnad`)

### Timeout no processamento

- PDF grande: o Gunicorn usa timeout de 300s
- Veja logs em Railway → **Deployments**

### Dados desatualizados após upload sem GitHub

- Sem push, só o container atual muda (efêmero no Railway)
- Sempre marque o envio ao GitHub em produção
