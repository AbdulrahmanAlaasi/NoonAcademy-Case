# Boon Academy — Intervention System

**Repo:** https://github.com/AbdulrahmanAlaasi/NoonAcademy-Case

Identifies at-risk students from daily metrics, scores them with an explainable
rule engine, and generates personalized facilitator action briefs (Arabic WhatsApp
message + English action) via Claude Haiku. Goal: lift intervention rate from
30% to 80%+ while keeping facilitator workload manageable.

## Setup & Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # required for real LLM briefs
python main.py
```

That's the only command. `main.py` self-installs dependencies from
`requirements.txt` on first run, then loads + cleans data, scores every student,
generates briefs (cached in SQLite, written to `outputs/`), and serves the
dashboard at http://localhost:8000.

CSVs go in `./data/`. All config via env vars (optionally a `.env` file — see
`.env.example`). Without an API key the pipeline still runs; LLM briefs fall back
to placeholders.

## What you see

Facilitator dashboard: summary stats, risk-sorted student list with campus
filter, per-student brief panel with copy-ready Arabic WhatsApp message.
