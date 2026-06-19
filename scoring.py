"""Boon Academy — rule-based risk scoring engine.

Pure, explainable, fast. NO LLM calls here. Each student is reduced to an
integer risk score (0-100), a tier, and a list of human-readable flags so a
facilitator can always see *why* a student surfaced.
"""

import logging

logger = logging.getLogger(__name__)

# Tier thresholds (inclusive lower bounds).
CRITICAL_THRESHOLD = 80
HIGH_THRESHOLD = 60
MEDIUM_THRESHOLD = 40

# Urgency multiplier applied when the next quiz is imminent.
URGENCY_DAYS = 6
URGENCY_MULTIPLIER = 1.2

# Feedback-loop penalty for a student who was already flagged and hasn't improved.
NO_IMPROVEMENT_PENALTY = 15
NO_IMPROVEMENT_FLAG = "No improvement since last intervention"


def _tier_for(score: int) -> str:
    """Map an integer score to its risk tier."""
    if score >= CRITICAL_THRESHOLD:
        return "Critical"
    if score >= HIGH_THRESHOLD:
        return "High"
    if score >= MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def score_student(student: dict) -> dict:
    """Score a merged student dict.

    Input: merged dict with fields from metrics + metadata + notes aggregate.
    Output: {risk_score: int, risk_tier: str, risk_flags: list[str]}.
    """
    score = 0
    flags: list[str] = []

    last_quiz = student.get("last_quiz_score")
    attendance = student.get("attendance_rate")
    session_min = student.get("session_attended_min")
    note_count = student.get("note_count", 0) or 0
    days_since_note = student.get("days_since_last_note")
    track = student.get("track")
    days_until_quiz = student.get("days_until_next_quiz")

    # Academic signals.
    if last_quiz is not None:
        if last_quiz < 50:
            score += 35
            flags.append("Critical quiz failure")
        elif last_quiz < 70:
            score += 20
            flags.append("Below passing threshold")

    # Engagement signals.
    if attendance is not None and attendance < 0.6:
        score += 25
        flags.append("Low attendance")
    if session_min is not None and session_min < 30:
        score += 15
        flags.append("Short sessions")

    # Contact / follow-up signals.
    if note_count == 0:
        score += 30
        flags.append("Never contacted")
    elif days_since_note is not None and days_since_note > 5:
        score += 20
        flags.append("Stale follow-up")

    # Cohort signal.
    if track == "Remedial":
        score += 10
        flags.append("Remedial track")

    # Feedback loop: previously flagged + no quiz improvement.
    if student.get("no_improvement"):
        score += NO_IMPROVEMENT_PENALTY
        flags.append(NO_IMPROVEMENT_FLAG)

    # Urgency multiplier when the next quiz is close.
    if days_until_quiz is not None and days_until_quiz <= URGENCY_DAYS:
        score = score * URGENCY_MULTIPLIER

    score = int(min(round(score), 100))

    return {"risk_score": score, "risk_tier": _tier_for(score), "risk_flags": flags}
