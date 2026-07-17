# Dashboard PNAD Ceará

Pipeline em Python para ler os quadros sintéticos da PNAD Contínua, gerar bases
CSV e disponibilizar um dashboard analítico do Ceará com comparação regional.

## Pasta `pnad/`

Coloque aqui os PDFs oficiais do IBGE:

`pnadc_YYYYQQ_trimestre_quadroSintetico.pdf`

Exemplos:

- `pnadc_202502_...` → abr-mai-jun/2025
- `pnadc_202503_...` → jul-ago-set/2025
- `pnadc_202504_...` → out-nov-dez/2025
- `pnadc_202601_...` → jan-fev-mar/2026

A série temporal usa automaticamente o **trimestre mais recente + os 3 anteriores**.

## Conteúdo

- `extract_series.py`: lê todos os PDFs em `pnad/` e gera a série do Ceará.
- `extract_data.py`: base detalhada do trimestre atual (com significância estatística).
- `extract_regional.py`: comparativo Brasil / Nordeste / estados (PDF mais recente em `pnad/`).
- `data/pnad_ce_serie.csv`: série temporal (atual + 3 anteriores).
- `data/pnad_ce_1tri2026.csv`: detalhamento do trimestre atual.
- `data/pnad_comparativo_1tri2026.csv`: comparação regional.
- `app.py`: dashboard com abas Análise do Ceará e Comparativo regional.
- `executar_dashboard.bat`: atualiza as bases e abre o painel.

## Instalação

```powershell
& "C:\Users\paulo\AppData\Local\Programs\Python\Python313\python.exe" -m pip install -r requirements.txt
```

## Atualizar as bases

```powershell
& "C:\Users\paulo\AppData\Local\Programs\Python\Python313\python.exe" extract_series.py
& "C:\Users\paulo\AppData\Local\Programs\Python\Python313\python.exe" extract_data.py
& "C:\Users\paulo\AppData\Local\Programs\Python\Python313\python.exe" extract_regional.py
```

## Executar o dashboard

```powershell
.\executar_dashboard.bat
```

Ou:

```powershell
& "C:\Users\paulo\AppData\Local\Programs\Python\Python313\python.exe" app.py
```

Acesse [http://127.0.0.1:8051](http://127.0.0.1:8051).

## Deploy (Railway)

Instruções em [`DEPLOY.md`](DEPLOY.md): Docker + GitHub + Railway.

A aba **Atualizar dados** permite upload do PDF do IBGE, regeneração dos CSVs
(série e comparativo) e envio automático ao GitHub (com token configurado).

Na aba **Análise do Ceará**, a seção 0 mostra gráficos de linha do trimestre atual
contra os três anteriores. A aba **Comparativo regional** confronta Ceará, Brasil,
Nordeste e demais estados do Nordeste.
