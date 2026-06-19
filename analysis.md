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
  cluster on a small set of students — the majority are invisible to the current
  workflow regardless of how they're doing. This single gap explains the 30%.
- **20% (40/200) failed Quiz 1 (score < 50), and 16 of them have zero notes.**
  The highest-need students are precisely the ones getting no follow-up — failure
  and silence overlap rather than cancel out.
- **Attendance is not the bottleneck — engagement quality is.** Only 1 student
  attends under 60% of sessions; disengagement instead shows up as short or
  zero-minute *recent* sessions (e.g. students dropping from 90 to 20 min) and
  missed practice. So risk is driven by quiz failure + no contact, with the next
  quiz 6 days out forcing urgency now.

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
  this snapshot all 52 at-risk (Critical+High) students get a brief.

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
