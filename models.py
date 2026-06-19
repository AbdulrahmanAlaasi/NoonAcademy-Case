"""Boon Academy — SQLAlchemy 2.x ORM models and DB session helpers.

DATABASE_URL comes from the environment (defaults to local SQLite). Tables are
created idempotently via init_db() / create_all() on startup.
"""

import logging
import os

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Student(Base):
    """One row per student — identity and contact metadata."""

    __tablename__ = "students"

    student_id = Column(String, primary_key=True)
    name = Column(String)
    campus = Column(String)
    track = Column(String)
    facilitator_id = Column(String)
    phone_number = Column(String, nullable=True)


class DailyMetric(Base):
    """Most-recent daily metrics snapshot for a student."""

    __tablename__ = "daily_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String, ForeignKey("students.student_id"))
    date = Column(String)
    quiz_score = Column(Float, nullable=True)
    session_attended_min = Column(Float)
    attendance_rate = Column(Float)
    last_quiz_score = Column(Float, nullable=True)
    days_until_next_quiz = Column(Integer)


class FacilitatorNote(Base):
    """A single facilitator note about a student."""

    __tablename__ = "facilitator_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String, ForeignKey("students.student_id"))
    date = Column(String)
    note_type = Column(String)
    note_content = Column(String)
    facilitator_id = Column(String)


class InterventionBrief(Base):
    """A scored + (optionally) LLM-generated intervention brief for a student."""

    __tablename__ = "intervention_briefs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String, ForeignKey("students.student_id"))
    risk_tier = Column(String)
    risk_score = Column(Integer)
    risk_flags = Column(JSON)
    whatsapp_message = Column(String)
    action_recommendation = Column(String)
    reasoning = Column(String)
    data_hash = Column(String)
    generated_at = Column(DateTime)
    campus = Column(String)


def get_engine():
    """Create an engine from DATABASE_URL (default local SQLite)."""
    url = os.getenv("DATABASE_URL", "sqlite:///boon.db")
    return create_engine(url, future=True)


# Module-level engine + session factory, shared by the pipeline and the API.
engine = get_engine()
SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)


def init_db() -> None:
    """Create all tables if they don't exist (idempotent)."""
    Base.metadata.create_all(engine)
    logger.info("Database tables ready at %s", engine.url)
