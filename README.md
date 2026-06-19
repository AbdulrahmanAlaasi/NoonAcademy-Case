# Boon Academy — Intervention System

Identifies at-risk students from daily metrics, scores them with an explainable
rule engine, and generates personalized facilitator action briefs (Arabic
WhatsApp message + English action) via Claude Haiku. Goal: lift intervention
rate from 30% to 80%+ while keeping facilitator workload manageable.

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # required for real LLM briefs
python main.py
```

That's the only command. `main.py` self-installs dependencies from
`requirements.txt` on first run, loads + cleans the data, scores every student,
generates briefs (cached in the DB, written to `outputs/`), and serves the
dashboard at http://localhost:8000.

The three source CSVs live in `./data/` (`student_daily_metrics.csv`,
`student_metadata.csv`, `facilitator_notes.csv`). Config is read from env vars,
optionally via a `.env` file — see `.env.example`. Without an API key the
pipeline still runs and the dashboard works (briefs fall back to placeholders).

## What you see

A facilitator dashboard: summary stats, a risk-sorted student list with campus
filter, and a per-student brief panel with the copy-ready WhatsApp message.
