# CLAUDE.md — Boon Academy Intervention System

> Read this entire file before touching any code. It is the single source of truth.

---

## What This Is

A pipeline + dashboard that identifies at-risk students at Boon Academy and generates
personalized facilitator action briefs. Goal: raise intervention rate from 30% → 80%+.

**Evaluator:** Noon Academy (real company). **Problem scenario:** Boon Academy (fictional).
All code comments, README, and analysis.md reference "Boon Academy" for the problem.

---

## Single Entry Point

```
python main.py
```

This must: load data → validate → score → persist → generate LLM briefs → start FastAPI server.
Server starts on `PORT` (default 8000). Dashboard at http://localhost:8000.

---

## Folder Structure

```
.
├── CLAUDE.md               ← you are here
├── README.md               ← ≤30 lines, hard limit
├── main.py                 ← bootstrap + one-time pipeline run + uvicorn start
├── pipeline.py             ← pipeline orchestration (imported by main + api)
├── data.py                 ← CSV loading + cleaning
├── models.py               ← SQLAlchemy ORM models
├── scoring.py              ← rule-based risk engine (NO LLM here)
├── llm.py                  ← Claude Haiku integration + caching
├── api.py                  ← FastAPI app + routes (incl. /api/pipeline/run)
├── requirements.txt
├── .env.example
├── data/                   ← CSVs go here
│   ├── student_daily_metrics.csv
│   ├── facilitator_notes.csv
│   └── student_metadata.csv
├── dashboard/
│   └── templates/
│       └── index.html      ← DO NOT TOUCH — built by Cowork
├── outputs/                ← LLM brief JSONs written here
│   └── .gitkeep
└── analysis.md             ← written after code is confirmed working
```

---

## Environment Variables

All paths and secrets come from env vars. Use `python-dotenv` to load `.env`.

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | required | Claude Haiku API key |
| `DATABASE_URL` | `sqlite:///boon.db` | Swap to postgres:// for scale |
| `DATA_DIR` | `./data` | Base path for CSVs |
| `STUDENTS_CSV` | `{DATA_DIR}/student_daily_metrics.csv` | |
| `METADATA_CSV` | `{DATA_DIR}/student_metadata.csv` | |
| `NOTES_CSV` | `{DATA_DIR}/facilitator_notes.csv` | |
| `FEEDBACK_LOG` | `./intervention_log.json` | Feedback loop state |
| `MAX_STUDENTS_PER_BRIEF` | `50` | Cap for Medium/High tiers; Critical always included |
| `PORT` | `8000` | uvicorn port |

Resolve CSV paths: `os.getenv("STUDENTS_CSV", os.path.join(os.getenv("DATA_DIR", "./data"), "student_daily_metrics.csv"))` — same pattern for all three.

---

## Data Schema

### student_daily_metrics.csv
Columns (Day 14 snapshot — most recent row per student is the current state):
- `student_id` — string
- `date` — YYYY-MM-DD
- `quiz_score` — float, 0–100, null if no quiz that day
- `session_attended_min` — float, minutes in session; 3 rows are null → fill with 0
- `attendance_rate` — float, 0.0–1.0 (proportion of sessions attended)
- `last_quiz_score` — float, UNDOCUMENTED COLUMN — most recent quiz score regardless of date
- `days_until_next_quiz` — int, UNDOCUMENTED COLUMN — currently 6 for all students

Use the **most recent row per student** (max date) as the current state.

### student_metadata.csv
- `student_id` — string (join key)
- `name` — string
- `campus` — string (5 campuses)
- `track` — "Regular" or "Remedial"
- `facilitator_id` — string
- `phone_number` — string; 2 are malformed (one is an email address) → normalize: strip non-digits, log warning, set to null if invalid

### facilitator_notes.csv
- `student_id` — string
- `date` — YYYY-MM-DD
- `note_type` — string
- `note_content` — string
- `facilitator_id` — string

Computed per student: `note_count`, `last_note_date`, `days_since_last_note`.
32 students have zero notes ever.

---

## data.py

```python
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load and clean all 3 CSVs. Returns (metrics, metadata, notes)."""
```

- Read paths from env vars (see above)
- Fill `session_attended_min` nulls with 0, log warning
- Normalize phone numbers: keep digits only via regex, set null if result is not 9–15 digits, log warning
- Use most recent row per student in metrics (groupby student_id, keep max date)
- Return cleaned DataFrames — never raise on bad data, always log and continue

---

## models.py

Use SQLAlchemy 2.x declarative style. `DATABASE_URL` from env.

Tables:
- `students` — student_id (PK), name, campus, track, facilitator_id, phone_number
- `daily_metrics` — id (PK), student_id (FK), date, quiz_score, session_attended_min, attendance_rate, last_quiz_score, days_until_next_quiz
- `facilitator_notes` — id (PK), student_id (FK), date, note_type, note_content, facilitator_id
- `intervention_briefs` — id (PK), student_id (FK), risk_tier, risk_score, risk_flags (JSON), whatsapp_message, action_recommendation, reasoning, data_hash, generated_at, campus

`create_all()` on startup — idempotent.

---

## scoring.py

**Rule-based only. No LLM. Explainable and fast.**

```python
def score_student(student: dict) -> dict:
    """
    Input: merged dict with fields from metrics + metadata + notes aggregate.
    Output: {risk_score: int, risk_tier: str, risk_flags: list[str]}
    """
```

Scoring rules (additive):
| Condition | Points | Flag label |
|---|---|---|
| `last_quiz_score < 50` | +35 | "Critical quiz failure" |
| `last_quiz_score` 50–69 | +20 | "Below passing threshold" |
| `attendance_rate < 0.6` | +25 | "Low attendance" |
| `session_attended_min < 30` (avg) | +15 | "Short sessions" |
| `note_count == 0` | +30 | "Never contacted" |
| `days_since_last_note > 5` (and note_count > 0) | +20 | "Stale follow-up" |
| `track == "Remedial"` | +10 | "Remedial track" |

Urgency: if `days_until_next_quiz <= 6`, multiply final score by 1.2 (cap at 100).

Tier thresholds:
- ≥ 80 → "Critical"
- 60–79 → "High"
- 40–59 → "Medium"
- < 40 → "Low"

Return `risk_score` as int (0–100), `risk_tier` as string, `risk_flags` as list of triggered flag labels.

---

## llm.py

Model: `claude-haiku-4-5-20251001` via `anthropic` Python SDK.

### Caching Strategy
Compute `data_hash = sha256(f"{student_id}|{last_quiz_score}|{attendance_rate}|{days_since_last_note}|{note_count}".encode()).hexdigest()`.
Before calling API: query `intervention_briefs` table for existing row with same `student_id` and `data_hash`.
If found and not older than 7 days → return cached. Else → call API, persist new row.

### Which Students Get Briefs
- ALL Critical-tier students (regardless of cap)
- High + Medium: up to `MAX_STUDENTS_PER_BRIEF` total, sorted by risk_score desc
- Low: skip

### Prompt
System: "You are an educational intervention assistant for Boon Academy. You help facilitators support at-risk students."

User prompt (build from student dict):
```
Student: {name}, Campus: {campus}, Track: {track}
Risk: {risk_tier} (score: {risk_score}/100)
Flags: {", ".join(risk_flags)}
Quiz score: {last_quiz_score}/100 | Attendance: {attendance_rate:.0%}
Days without facilitator contact: {days_since_last_note if note_count > 0 else "never contacted"}
Days until next quiz: {days_until_next_quiz}

Generate a JSON response with exactly these keys:
- "whatsapp_message": A warm, encouraging Arabic WhatsApp message (2-3 sentences) the facilitator can send directly to the student. Use the student's name. Be specific about the quiz.
- "action": One clear English action the facilitator should take today (1 sentence).
- "reasoning": Why this student is prioritized right now (1-2 sentences, English).
```

Parse JSON from response. If parse fails, log and return placeholder strings (never crash).

### Output Files
Write each brief to `outputs/{student_id}.json`:
```json
{
  "student_id": "...",
  "name": "...",
  "campus": "...",
  "risk_tier": "...",
  "risk_score": 0,
  "risk_flags": [],
  "whatsapp_message": "...",
  "action": "...",
  "reasoning": "...",
  "generated_at": "ISO timestamp"
}
```

---

## Feedback Loop

Before scoring, read `FEEDBACK_LOG` (JSON array) if it exists.
Build set of student_ids that were recommended in the previous run.

In scoring: if student_id in previous recommendations AND `last_quiz_score` has not improved since last run → add +15 to risk_score (flag: "No improvement since last intervention").

After generating briefs, append to `FEEDBACK_LOG`:
```json
[{"student_id": "...", "date": "YYYY-MM-DD", "risk_tier": "...", "recommended": true}]
```
Append, don't overwrite. Keep last 30 days of entries.

---

## api.py — FastAPI Routes

```
GET /                          → serve dashboard/templates/index.html (Jinja2Templates)
GET /api/students              → list all students with risk data, optional ?campus=X filter
GET /api/summary               → {total, by_tier: {Critical, High, Medium, Low}, intervention_rate}
GET /api/brief/{student_id}    → full brief for one student including LLM output
```

Response schema for `/api/students` items:
```json
{
  "student_id": "s001",
  "name": "...",
  "campus": "...",
  "track": "...",
  "facilitator_id": "...",
  "risk_tier": "Critical",
  "risk_score": 87,
  "risk_flags": ["Never contacted", "Critical quiz failure"],
  "last_quiz_score": 34,
  "attendance_rate": 0.6,
  "has_brief": true
}
```

For `/api/summary`, `intervention_rate` = students with a brief generated / total students with Critical or High risk.

Mount `dashboard/` as static files for any CSS/JS assets if needed.

---

## main.py

```python
def main():
    load_dotenv()
    metrics, metadata, notes = load_data()
    students = merge_student_data(metrics, metadata, notes)  # returns list of dicts
    scored = [score_student(s) for s in students]
    persist_to_db(scored)           # upsert into SQLAlchemy models
    generate_briefs(scored)         # llm.py — respects cache
    uvicorn.run("api:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)

if __name__ == "__main__":
    main()
```

---

## requirements.txt (exact packages)

```
anthropic
fastapi
uvicorn[standard]
sqlalchemy
pandas
python-dotenv
jinja2
```

---

## .env.example

```
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=sqlite:///boon.db
DATA_DIR=./data
FEEDBACK_LOG=./intervention_log.json
MAX_STUDENTS_PER_BRIEF=50
PORT=8000
```

---

## README.md (≤30 lines — write this last)

Must cover: what it does, setup (pip install -r requirements.txt, copy .env.example → .env, add API key), single run command, what you see.

---

## Quality Rules

- No hardcoded paths, API keys, or model names — all from env vars or constants at top of file
- No LLM calls in scoring.py ever
- Every function has a docstring
- Log with Python `logging` module (not print) at INFO level
- `main.py` sets up logging format at startup
- System never crashes on bad input data — catch, log, continue
- `analysis.md` is NOT generated by code — it's a human-written markdown file

---

## What Cowork Already Built

- `CLAUDE.md` — this file
- `dashboard/templates/index.html` — do not regenerate or modify

## What Claude Code Must Build

All Python files, `requirements.txt`, `.env.example`, `README.md`.
