"""Boon Academy — pipeline orchestration.

Extracted from main.py so it can be triggered both at startup and on-demand
via the POST /api/pipeline/run endpoint without circular imports.
"""

import json
import logging
import os
from datetime import datetime, timedelta

import pandas as pd

from data import load_data
from llm import generate_briefs
from models import DailyMetric, SessionLocal, Student
from scoring import score_student

logger = logging.getLogger(__name__)

FEEDBACK_RETENTION_DAYS = 30

# Module-level state so the API can check whether a run is in progress.
_running = False
_last_run: datetime | None = None


def is_running() -> bool:
    """Return True if the pipeline is currently executing."""
    return _running


def last_run() -> datetime | None:
    """Return the timestamp of the last completed pipeline run."""
    return _last_run


def run_pipeline() -> None:
    """Load data → score → persist → generate briefs → write feedback.

    Safe to call from a background thread. Sets module-level state so the
    /api/pipeline/status endpoint can report progress.
    """
    global _running, _last_run
    if _running:
        logger.warning("Pipeline already running — skipping duplicate trigger")
        return

    _running = True
    try:
        feedback_log = os.getenv("FEEDBACK_LOG", "./intervention_log.json")

        metrics, metadata, notes = load_data()
        students = merge_student_data(metrics, metadata, notes)
        apply_feedback(students, feedback_log)

        scored = []
        for student in students:
            student.update(score_student(student))
            scored.append(student)

        tiers: dict[str, int] = {}
        for s in scored:
            tiers[s["risk_tier"]] = tiers.get(s["risk_tier"], 0) + 1
        logger.info("Scored students by tier: %s", tiers)

        persist_to_db(scored)
        generate_briefs(scored)
        write_feedback(scored, feedback_log)

        _last_run = datetime.now()
        logger.info("Pipeline complete at %s", _last_run.isoformat())
    finally:
        _running = False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _snapshot_date(metrics: pd.DataFrame) -> datetime:
    """Reference 'today' for recency math — the latest metric date (Day 14)."""
    if "date" in metrics.columns and not metrics["date"].isna().all():
        return pd.to_datetime(metrics["date"]).max()
    return datetime.now()


def _note_aggregates(notes: pd.DataFrame, snapshot: datetime) -> dict:
    """Per-student note_count, last_note_date, days_since_last_note."""
    agg: dict[str, dict] = {}
    if notes.empty or "student_id" not in notes.columns:
        return agg
    for sid, group in notes.groupby("student_id"):
        dates = pd.to_datetime(group["date"], errors="coerce").dropna()
        last = dates.max() if not dates.empty else None
        agg[sid] = {
            "note_count": len(group),
            "last_note_date": last.strftime("%Y-%m-%d") if last is not None else None,
            "days_since_last_note": (snapshot - last).days if last is not None else None,
        }
    return agg


def _load_feedback(path: str) -> dict:
    """Read previous-run recommendations: {student_id: last_quiz_score}."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            entries = json.load(fh)
        return {
            e["student_id"]: e.get("last_quiz_score")
            for e in entries
            if e.get("recommended")
        }
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read feedback log %s: %s", path, exc)
        return {}


def merge_student_data(metrics, metadata, notes) -> list[dict]:
    """Merge the three sources into a list of per-student dicts for scoring."""
    snapshot = _snapshot_date(metrics)
    note_agg = _note_aggregates(notes, snapshot)

    meta_by_id = {row["student_id"]: row for row in metadata.to_dict("records")}
    metric_by_id = {row["student_id"]: row for row in metrics.to_dict("records")}

    students = []
    for sid in meta_by_id:
        merged = {"student_id": sid}
        merged.update(meta_by_id.get(sid, {}))
        merged.update(metric_by_id.get(sid, {}))
        merged.update(note_agg.get(sid, {"note_count": 0, "days_since_last_note": None}))
        for key, value in list(merged.items()):
            if isinstance(value, float) and pd.isna(value):
                merged[key] = None
        students.append(merged)

    logger.info("Merged %d students", len(students))
    return students


def apply_feedback(students: list[dict], path: str) -> None:
    """Mark students recommended last run whose quiz score hasn't improved."""
    previous = _load_feedback(path)
    for student in students:
        sid = student["student_id"]
        if sid in previous:
            prev_score = previous[sid]
            curr_score = student.get("last_quiz_score")
            if (
                prev_score is not None
                and curr_score is not None
                and curr_score <= prev_score
            ):
                student["no_improvement"] = True


def persist_to_db(scored: list[dict]) -> None:
    """Upsert students and their metrics into the database."""
    with SessionLocal() as session:
        session.query(DailyMetric).delete()
        session.query(Student).delete()
        for s in scored:
            session.merge(
                Student(
                    student_id=s["student_id"],
                    name=s.get("name"),
                    campus=s.get("campus"),
                    track=s.get("track"),
                    facilitator_id=s.get("facilitator_id"),
                    phone_number=s.get("phone_number"),
                )
            )
            session.add(
                DailyMetric(
                    student_id=s["student_id"],
                    date=s.get("date"),
                    quiz_score=s.get("quiz_score"),
                    session_attended_min=s.get("session_attended_min") or 0,
                    attendance_rate=s.get("attendance_rate"),
                    last_quiz_score=s.get("last_quiz_score"),
                    days_until_next_quiz=s.get("days_until_next_quiz"),
                )
            )
        session.commit()
    logger.info("Persisted %d students to the database", len(scored))


def write_feedback(scored: list[dict], path: str) -> None:
    """Append this run's recommendations to the feedback log (last 30 days)."""
    today = datetime.now()
    existing = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                existing = json.load(fh)
        except (OSError, json.JSONDecodeError):
            existing = []

    cutoff = today - timedelta(days=FEEDBACK_RETENTION_DAYS)
    existing = [
        e for e in existing
        if _safe_date(e.get("date")) is None or _safe_date(e.get("date")) >= cutoff
    ]

    for s in scored:
        if s["risk_tier"] in ("Critical", "High", "Medium"):
            existing.append(
                {
                    "student_id": s["student_id"],
                    "date": today.strftime("%Y-%m-%d"),
                    "risk_tier": s["risk_tier"],
                    "last_quiz_score": s.get("last_quiz_score"),
                    "recommended": True,
                }
            )

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, ensure_ascii=False, indent=2)
    logger.info("Updated feedback log %s", path)


def _safe_date(value):
    """Parse a YYYY-MM-DD string to datetime, or None."""
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
