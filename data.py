"""Boon Academy — CSV loading and cleaning.

Loads the three source CSVs, maps the real-world column names onto the canonical
schema the rest of the pipeline expects, repairs the known messy fields (null
session minutes, malformed phone numbers), and reduces daily metrics to one
enriched row per student (most-recent quiz state + attendance/session
aggregates). Never raises on bad data: it logs a warning and keeps going so the
pipeline always produces something usable.
"""

import logging
import os
import re

import pandas as pd

logger = logging.getLogger(__name__)

# The source CSVs use product-facing column names; map them to the canonical
# fields scoring.py / main.py expect. Anything not listed is passed through.
METRICS_COLUMN_MAP = {}  # canonical already: session_attended_min, last_quiz_score, days_until_next_quiz
METADATA_COLUMN_MAP = {
    "student_name": "name",
    "campus_id": "campus",
    "learning_track": "track",
    "facilitator_email": "facilitator_id",
    "parent_phone": "phone_number",
}
NOTES_COLUMN_MAP = {
    "note_text": "note_content",
    "facilitator_email": "facilitator_id",
}

SESSION_FULL_MINUTES = 90  # a full morning session


def _csv_path(env_var: str, filename: str) -> str:
    """Resolve a CSV path from its env var, falling back to DATA_DIR/filename."""
    return os.getenv(env_var, os.path.join(os.getenv("DATA_DIR", "./data"), filename))


def _rename(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Rename source columns to canonical names where present."""
    return df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})


def _normalize_phone(raw) -> str | None:
    """Strip a phone number to digits only; return None if not 9-15 digits."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    digits = re.sub(r"\D", "", str(raw))
    if 9 <= len(digits) <= 15:
        return digits
    logger.warning("Dropping malformed phone number: %r", raw)
    return None


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load and clean all 3 CSVs. Returns (metrics, metadata, notes)."""
    metrics = _load_metrics(_csv_path("STUDENTS_CSV", "student_daily_metrics.csv"))
    metadata = _load_metadata(_csv_path("METADATA_CSV", "student_metadata.csv"))
    notes = _load_notes(_csv_path("NOTES_CSV", "facilitator_notes.csv"))
    return metrics, metadata, notes


def _load_metrics(path: str) -> pd.DataFrame:
    """Load daily metrics and reduce to one enriched row per student.

    The current quiz state (last_quiz_score, days_until_next_quiz, date) comes
    from each student's most-recent row. Engagement signals are aggregated over
    all 14 days: session_attended_min is the per-day average, and attendance_rate
    is the fraction of session days the student actually showed up (minutes > 0).
    """
    try:
        df = _rename(pd.read_csv(path), METRICS_COLUMN_MAP)
    except Exception as exc:  # noqa: BLE001 — never crash on bad input
        logger.error("Could not read metrics CSV %s: %s", path, exc)
        return pd.DataFrame()

    if "session_attended_min" in df.columns:
        null_count = int(df["session_attended_min"].isna().sum())
        if null_count:
            logger.warning("Filling %d null session_attended_min with 0", null_count)
            df["session_attended_min"] = df["session_attended_min"].fillna(0)

    if not {"student_id", "date"}.issubset(df.columns):
        logger.error("Metrics CSV missing student_id/date columns")
        return df.reset_index(drop=True)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    rows = []
    for sid, group in df.groupby("student_id"):
        group = group.sort_values("date")
        latest = group.iloc[-1]
        minutes = group["session_attended_min"].fillna(0)
        present = (minutes > 0).sum()
        total = len(group)
        rows.append(
            {
                "student_id": sid,
                "date": latest["date"].strftime("%Y-%m-%d") if pd.notna(latest["date"]) else None,
                "quiz_score": latest.get("quiz_score"),
                "session_attended_min": round(float(minutes.mean()), 1),
                "attendance_rate": round(present / total, 2) if total else None,
                "last_quiz_score": latest.get("last_quiz_score"),
                "days_until_next_quiz": latest.get("days_until_next_quiz"),
            }
        )

    result = pd.DataFrame(rows)
    logger.info("Loaded metrics for %d students from %s", len(result), path)
    return result


def _load_metadata(path: str) -> pd.DataFrame:
    """Load student metadata, map columns, and normalize phone numbers."""
    try:
        df = _rename(pd.read_csv(path), METADATA_COLUMN_MAP)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not read metadata CSV %s: %s", path, exc)
        return pd.DataFrame()

    if "phone_number" in df.columns:
        df["phone_number"] = df["phone_number"].apply(_normalize_phone)

    logger.info("Loaded %d student metadata rows from %s", len(df), path)
    return df.reset_index(drop=True)


def _load_notes(path: str) -> pd.DataFrame:
    """Load facilitator notes (all notes kept; columns mapped to canonical)."""
    try:
        df = _rename(pd.read_csv(path), NOTES_COLUMN_MAP)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not read notes CSV %s: %s", path, exc)
        return pd.DataFrame()

    if "note_type" not in df.columns:
        df["note_type"] = "note"  # source notes are untyped
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")

    logger.info("Loaded %d facilitator notes from %s", len(df), path)
    return df.reset_index(drop=True)
