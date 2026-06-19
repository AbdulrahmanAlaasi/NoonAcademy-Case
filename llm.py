"""Boon Academy — Claude Haiku integration for facilitator briefs.

Generates a warm Arabic WhatsApp message, an English action, and reasoning for
each prioritized student. Results are cached in the intervention_briefs table
keyed by (student_id, data_hash) so unchanged students never re-hit the API.
Every brief is also written to outputs/{student_id}.json.

Never crashes on an API or parse failure: it logs and falls back to placeholder
strings so the pipeline always completes.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from models import InterventionBrief, SessionLocal

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
CACHE_MAX_AGE_DAYS = 7
OUTPUTS_DIR = "outputs"

SYSTEM_PROMPT = (
    "You are an educational intervention assistant for Boon Academy. "
    "You help facilitators support at-risk students."
)


def compute_data_hash(student: dict) -> str:
    """Stable hash of the fields that, if changed, should invalidate a brief."""
    raw = (
        f"{student.get('student_id')}|{student.get('last_quiz_score')}|"
        f"{student.get('attendance_rate')}|{student.get('days_since_last_note')}|"
        f"{student.get('note_count')}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _select_students(scored: list[dict], cap: int) -> list[dict]:
    """All Critical students, plus top High/Medium up to the cap. Low is skipped."""
    critical = [s for s in scored if s["risk_tier"] == "Critical"]
    high_medium = [s for s in scored if s["risk_tier"] in ("High", "Medium")]
    high_medium.sort(key=lambda s: s["risk_score"], reverse=True)
    return critical + high_medium[:cap]


def _build_prompt(student: dict) -> str:
    """Render the user prompt from a scored student dict."""
    note_count = student.get("note_count", 0) or 0
    days_since = student.get("days_since_last_note")
    contact = days_since if note_count > 0 else "never contacted"
    attendance = student.get("attendance_rate") or 0
    return (
        f"Student: {student.get('name')}, Campus: {student.get('campus')}, "
        f"Track: {student.get('track')}\n"
        f"Risk: {student.get('risk_tier')} (score: {student.get('risk_score')}/100)\n"
        f"Flags: {', '.join(student.get('risk_flags', []))}\n"
        f"Quiz score: {student.get('last_quiz_score')}/100 | "
        f"Attendance: {attendance:.0%}\n"
        f"Days without facilitator contact: {contact}\n"
        f"Days until next quiz: {student.get('days_until_next_quiz')}\n\n"
        "Generate a JSON response with exactly these keys:\n"
        '- "whatsapp_message": A warm, encouraging Arabic WhatsApp message '
        "(2-3 sentences) the facilitator can send directly to the student. "
        "Use the student's name. Be specific about the quiz.\n"
        '- "action": One clear English action the facilitator should take today '
        "(1 sentence).\n"
        '- "reasoning": Why this student is prioritized right now (1-2 sentences, '
        "English)."
    )


def _placeholder(student: dict) -> dict:
    """Safe fallback brief content when the LLM is unavailable or unparseable."""
    return {
        "whatsapp_message": f"مرحباً {student.get('name', '')}، تواصل مع ميسّرك لمتابعة تقدمك قبل الاختبار القادم.",
        "action": "Contact this student today to review quiz performance and plan support.",
        "reasoning": "Flagged by the rule-based engine; LLM brief unavailable.",
    }


def _parse_response(text: str) -> dict | None:
    """Extract the JSON object from a model response, tolerating surrounding text."""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed to parse LLM JSON: %s", exc)
        return None


def _cached_brief(session, student_id: str, data_hash: str):
    """Return a fresh cached brief row, or None."""
    row = (
        session.query(InterventionBrief)
        .filter_by(student_id=student_id, data_hash=data_hash)
        .order_by(InterventionBrief.generated_at.desc())
        .first()
    )
    if row is None or row.generated_at is None:
        return None
    age_days = (datetime.now(timezone.utc) - _aware(row.generated_at)).days
    if age_days <= CACHE_MAX_AGE_DAYS:
        return row
    return None


def _aware(dt: datetime) -> datetime:
    """Treat naive timestamps as UTC for age comparison."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _get_client():
    """Construct an Anthropic client, or None if the SDK/key is unavailable."""
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic SDK not installed; using placeholder briefs")
        return None
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY not set; using placeholder briefs")
        return None
    return anthropic.Anthropic()


def _call_llm(client, student: dict) -> dict:
    """Call Claude Haiku for one student; fall back to placeholder on any failure."""
    if client is None:
        return _placeholder(student)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(student)}],
        )
        parsed = _parse_response(resp.content[0].text)
        if parsed and {"whatsapp_message", "action", "reasoning"} <= parsed.keys():
            return parsed
        logger.warning("LLM response missing keys for %s", student.get("student_id"))
    except Exception as exc:  # noqa: BLE001 — never crash the pipeline
        logger.error("LLM call failed for %s: %s", student.get("student_id"), exc)
    return _placeholder(student)


def _write_output(student: dict, brief: dict, generated_at: str) -> None:
    """Write a brief JSON to outputs/{student_id}.json."""
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    payload = {
        "student_id": student.get("student_id"),
        "name": student.get("name"),
        "campus": student.get("campus"),
        "risk_tier": student.get("risk_tier"),
        "risk_score": student.get("risk_score"),
        "risk_flags": student.get("risk_flags", []),
        "whatsapp_message": brief["whatsapp_message"],
        "action": brief["action"],
        "reasoning": brief["reasoning"],
        "generated_at": generated_at,
    }
    path = os.path.join(OUTPUTS_DIR, f"{student.get('student_id')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def generate_briefs(scored: list[dict]) -> None:
    """Generate (or reuse cached) briefs for the prioritized students.

    Persists each brief to the intervention_briefs table and writes the
    corresponding outputs/{student_id}.json file.
    """
    cap = int(os.getenv("MAX_STUDENTS_PER_BRIEF", "50"))
    selected = _select_students(scored, cap)
    logger.info("Generating briefs for %d students", len(selected))

    client = _get_client()
    generated = cached = 0

    with SessionLocal() as session:
        for student in selected:
            data_hash = compute_data_hash(student)
            cached_row = _cached_brief(session, student["student_id"], data_hash)

            if cached_row is not None:
                brief = {
                    "whatsapp_message": cached_row.whatsapp_message,
                    "action": cached_row.action_recommendation,
                    "reasoning": cached_row.reasoning,
                }
                ts = _aware(cached_row.generated_at).isoformat()
                cached += 1
            else:
                brief = _call_llm(client, student)
                now = datetime.now(timezone.utc)
                ts = now.isoformat()
                session.add(
                    InterventionBrief(
                        student_id=student["student_id"],
                        risk_tier=student["risk_tier"],
                        risk_score=student["risk_score"],
                        risk_flags=student["risk_flags"],
                        whatsapp_message=brief["whatsapp_message"],
                        action_recommendation=brief["action"],
                        reasoning=brief["reasoning"],
                        data_hash=data_hash,
                        generated_at=now,
                        campus=student.get("campus"),
                    )
                )
                session.commit()
                generated += 1

            _write_output(student, brief, ts)

    logger.info("Briefs done — %d generated, %d from cache", generated, cached)
