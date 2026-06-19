"""Boon Academy — FastAPI app serving the facilitator dashboard + JSON API.

Reads scored students, metrics, and briefs from the database (populated by the
pipeline in main.py) and exposes the endpoints the dashboard expects.
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from models import DailyMetric, InterventionBrief, SessionLocal, Student

logger = logging.getLogger(__name__)

app = FastAPI(title="Boon Academy — Facilitator Dashboard")
DASHBOARD_HTML = os.path.join("dashboard", "templates", "index.html")

# At-risk tiers used to compute the intervention rate.
AT_RISK_TIERS = ("Critical", "High")


def _latest_metric(session, student_id: str):
    """Most recent metrics row for a student, or None."""
    return (
        session.query(DailyMetric)
        .filter_by(student_id=student_id)
        .order_by(DailyMetric.date.desc())
        .first()
    )


def _latest_brief(session, student_id: str):
    """Most recent brief for a student, or None."""
    return (
        session.query(InterventionBrief)
        .filter_by(student_id=student_id)
        .order_by(InterventionBrief.generated_at.desc())
        .first()
    )


@app.get("/", response_class=FileResponse)
def dashboard():
    """Serve the single-page facilitator dashboard (static HTML)."""
    return FileResponse(DASHBOARD_HTML, media_type="text/html")


@app.get("/api/students")
def list_students(campus: str | None = None):
    """List all students with risk data; optional ?campus= filter."""
    with SessionLocal() as session:
        query = session.query(Student)
        if campus and campus != "all":
            query = query.filter(Student.campus == campus)

        items = []
        for student in query.all():
            metric = _latest_metric(session, student.student_id)
            brief = _latest_brief(session, student.student_id)
            items.append(
                {
                    "student_id": student.student_id,
                    "name": student.name,
                    "campus": student.campus,
                    "track": student.track,
                    "facilitator_id": student.facilitator_id,
                    "risk_tier": brief.risk_tier if brief else "Low",
                    "risk_score": brief.risk_score if brief else 0,
                    "risk_flags": brief.risk_flags if brief else [],
                    "last_quiz_score": metric.last_quiz_score if metric else None,
                    "attendance_rate": metric.attendance_rate if metric else None,
                    "has_brief": brief is not None,
                }
            )
        return items


@app.get("/api/summary")
def summary():
    """Return totals, tier breakdown, and intervention rate."""
    with SessionLocal() as session:
        students = session.query(Student).all()
        by_tier = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
        at_risk = with_brief = 0

        for student in students:
            brief = _latest_brief(session, student.student_id)
            tier = brief.risk_tier if brief else "Low"
            by_tier[tier] = by_tier.get(tier, 0) + 1
            if tier in AT_RISK_TIERS:
                at_risk += 1
                if brief is not None:
                    with_brief += 1

        rate = (with_brief / at_risk) if at_risk else 0.0
        return {
            "total": len(students),
            "by_tier": by_tier,
            "intervention_rate": rate,
        }


@app.get("/api/brief/{student_id}")
def get_brief(student_id: str):
    """Return the full brief for one student, including LLM output."""
    with SessionLocal() as session:
        student = session.get(Student, student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")
        brief = _latest_brief(session, student_id)
        if brief is None:
            raise HTTPException(status_code=404, detail="No brief for student")
        metric = _latest_metric(session, student_id)
        return {
            "student_id": student.student_id,
            "name": student.name,
            "campus": student.campus,
            "track": student.track,
            "facilitator_id": student.facilitator_id,
            "risk_tier": brief.risk_tier,
            "risk_score": brief.risk_score,
            "risk_flags": brief.risk_flags,
            "last_quiz_score": metric.last_quiz_score if metric else None,
            "attendance_rate": metric.attendance_rate if metric else None,
            "whatsapp_message": brief.whatsapp_message,
            "action": brief.action_recommendation,
            "reasoning": brief.reasoning,
            "generated_at": brief.generated_at.isoformat() if brief.generated_at else None,
        }
