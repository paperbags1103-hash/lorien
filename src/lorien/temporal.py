"""Temporal utilities for lorien — freshness scoring and knowledge evolution."""
from __future__ import annotations

import math
from datetime import datetime, timezone


# Half-life in days: after this many days without confirmation, freshness = 0.5
FRESHNESS_HALF_LIFE_DAYS = 30.0


def freshness_score(last_confirmed: str, half_life_days: float = FRESHNESS_HALF_LIFE_DAYS) -> float:
    """Compute a 0.0–1.0 freshness score based on how recently a fact was confirmed.

    Uses exponential decay: score = 2^(-age_days / half_life_days)
    - Confirmed today → score ≈ 1.0
    - Confirmed 30 days ago → score ≈ 0.5
    - Confirmed 90 days ago → score ≈ 0.125

    Args:
        last_confirmed: ISO 8601 timestamp string (UTC)
        half_life_days: Days until score halves (default: 30)

    Returns:
        Float in [0.0, 1.0]
    """
    if not last_confirmed:
        return 0.5  # unknown age → neutral

    try:
        ts = datetime.fromisoformat(last_confirmed)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
        return math.pow(2.0, -age_days / half_life_days)
    except (ValueError, TypeError):
        return 0.5


def is_stale(
    last_confirmed: str,
    max_age_days: float = 90.0,
    min_confidence: float = 0.3,
    confidence: float = 1.0,
) -> bool:
    """Return True if a fact should be considered stale.

    A fact is stale when BOTH conditions hold:
    - Age since last_confirmed > max_age_days
    - Confidence < min_confidence
    """
    if not last_confirmed:
        return False

    try:
        ts = datetime.fromisoformat(last_confirmed)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
        return age_days > max_age_days and confidence < min_confidence
    except (ValueError, TypeError):
        return False


def classify_temporal_relation(
    text_a: str,
    created_at_a: str,
    text_b: str,
    created_at_b: str,
    same_subject_predicate: bool = False,
    time_gap_threshold_days: float = 7.0,
) -> str:
    """Classify whether two similar facts are a contradiction or temporal evolution.

    Rules:
    - Same subject+predicate AND time gap > threshold → "evolution" (SUPERSEDES)
    - Otherwise → "contradiction" (CONTRADICTS)

    Returns:
        "evolution" | "contradiction" | "unrelated"
    """
    if not (text_a and text_b):
        return "unrelated"

    if not same_subject_predicate:
        return "contradiction"

    try:
        ts_a = datetime.fromisoformat(created_at_a) if created_at_a else None
        ts_b = datetime.fromisoformat(created_at_b) if created_at_b else None

        if ts_a and ts_b:
            gap_days = abs((ts_a - ts_b).total_seconds()) / 86400.0
            if gap_days >= time_gap_threshold_days:
                return "evolution"
    except (ValueError, TypeError):
        pass

    return "contradiction"


def age_in_days(timestamp: str) -> float:
    """Return age in days since a timestamp (UTC). Returns 0.0 if invalid."""
    if not timestamp:
        return 0.0
    try:
        ts = datetime.fromisoformat(timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0)
    except (ValueError, TypeError):
        return 0.0
