# Boon Academy — Intervention System Analysis

## Diagnosis

The 30% intervention rate is a triage problem, not a motivation problem.
Facilitators already hold the data to know who's failing, but with 200 students
across 8 facilitators and no ranked, actionable view, attention flows to the
loudest cases while quiet at-risk students fall through. The fix is to remove
the two costs that actually block action: deciding *who* to contact and deciding
*what* to say.

## What you found in the data

- **62% of students (125/200) have never been contacted.** Facilitator notes
  cluster on 75 students; the other 125 are invisible to the current workflow
  regardless of performance. Notes also spike reactively — 74 of 180 total notes
  landed on the final day of the window, Day 14. This single gap explains the 30%.
- **41 students (20%) failed Quiz 1 with scores below 50 (average: 28.9/100),
  and 16 of them have zero facilitator notes ever.** The highest-need students
  are precisely the ones getting no follow-up — failure and silence overlap
  rather than cancel out.
- **93% of Remedial-track students (54/58) are scoring below the 70-point
  passing threshold.** The Remedial cohort is in near-total crisis: the track
  meant for students who need more support is receiving the same reactive,
  coverage-limited attention as the rest.
- **Attendance is not the bottleneck — quiz performance and contact silence are.**
  The next quiz is 6 days out for all students, making urgency uniform and
  making *today* the right moment to intervene.

## What you built and why

- **Rule-based risk engine** (`scoring.py`): explainable, instant, auditable — a
  facilitator sees the exact flags ("Critical quiz failure", "Never contacted")
  behind every score, building trust a black-box model wouldn't earn.
- **LLM briefs via Claude Haiku** (`llm.py`): turns each ranked student into a
  ready-to-send Arabic WhatsApp message + one English action, removing the "what
  do I say" cost; Haiku keeps it cheap and fast at campus scale.
- **Content-hash caching**: briefs are keyed by the fields that matter, so reruns
  only call the API for students whose situation actually changed (verified: a
  second run made 0 API calls).
- **Feedback loop** (`intervention_log.json`): students flagged last run whose
  quiz score hasn't improved get a score bump, so repeat-no-improvement cases
  escalate instead of being re-served identically.
- **Facilitator dashboard** (`api.py` + static HTML): risk-sorted list, campus
  filter, copy-ready message — built around how facilitators actually triage. On
  this snapshot, 57 briefs cover all 52 Critical+High students (100%) plus 5
  Medium-tier students, lifting the effective intervention rate to 100% of at-risk.

## What you cut and why

- **No trained ML model.** With 14 days of data and a hard need for
  explainability, a transparent rule engine beats a model that's harder to trust,
  tune, and defend to a facilitator. Rules are the right 80/20 here.
- **No real-time event streaming / message queue.** For 5–100 campuses a daily
  batch run is sufficient and far simpler to operate; Kafka-style infrastructure
  would be over-engineering for a cadence measured in days per quiz cycle.

## What you'd build next

**Closed-loop outcome tracking.** Today the feedback loop infers improvement from
quiz scores; the highest-value addition is recording whether a brief was *acted
on* (message sent, student replied) and tying that to the next quiz result. That
turns the system from "who to contact" into "which interventions actually move
scores" — the data that lets it improve and proves the 30%→80% lift is real.
