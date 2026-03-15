"""
BSR trend analytics.

Reads from the BSRSnapshot table (daily roll-ups in Postgres) and
from ClickHouse for high-resolution time-series when available.

compute_bsr_trend(asin_obj) → dict matching BSRTrendSerializer
"""
import logging
from datetime import date, timedelta
from typing import Optional

from django.db.models import Avg
from apps.products.models import ASIN, BSRSnapshot

logger = logging.getLogger(__name__)


def compute_bsr_trend(asin_obj: ASIN) -> dict:
    """
    Compute BSR YoY delta, trend direction, and a 90-day history series.
    Falls back to smaller windows (90d, 30d, or oldest) if 1-year data is missing.
    """
    today = date.today()
    ninety_days_ago = today - timedelta(days=90)

    # ── Current rank ──────────────────────────────────────────────────────
    current_rank = asin_obj.current_bsr

    # ── 90-day history for sparkline ──────────────────────────────────────
    history_qs = (
        BSRSnapshot.objects.filter(asin=asin_obj, date__gte=ninety_days_ago)
        .values("date", "bsr_rank")
        .order_by("date")
    )
    history = [{"date": str(row["date"]), "bsr": row["bsr_rank"]} for row in history_qs]

    # ── Comparison baseline (Best Available) ───────────────────────────────
    baseline_rank = _get_best_baseline_rank(asin_obj)

    yoy_change = None
    yoy_change_pct = None
    trend = "stable"

    if current_rank and baseline_rank:
        # Note: lower BSR is BETTER, so a negative delta = improvement
        yoy_change = current_rank - baseline_rank
        yoy_change_pct = round((yoy_change / baseline_rank) * 100, 1)
        trend = _classify_trend(yoy_change, baseline_rank)

    return {
        "currentRank": current_rank,
        "yoyChange": yoy_change,
        "yoyChangePct": yoy_change_pct,
        "trend": trend,
        "history": history,
    }


def _get_best_baseline_rank(asin_obj: ASIN) -> Optional[int]:
    """
    Find the best historical BSR rank for comparison.
    Tries 365d, 90d, 30d, then oldest available.
    """
    today = date.today()
    for days in [365, 90, 30]:
        val = _get_rank_around(asin_obj, today - timedelta(days=days))
        if val is not None:
            return val
    
    best_point = _get_oldest_rank(asin_obj)
    if best_point and best_point[0] < today:
        return best_point[1]
    return None


def _get_oldest_rank(asin_obj: ASIN) -> Optional[tuple[date, int]]:
    """Return (date, bsr) for the oldest snapshot we have."""
    oldest = BSRSnapshot.objects.filter(asin=asin_obj).order_by("date").first()
    if oldest:
        return oldest.date, oldest.bsr_rank
    return None


def _get_rank_around(asin_obj: ASIN, target_date: date, window_days: int = 7) -> Optional[int]:
    """
    Return the average BSR in a ±window window around a target date.
    Uses a rolling window to smooth out anomalous days.
    """
    start = target_date - timedelta(days=window_days)
    end = target_date + timedelta(days=window_days)

    result = BSRSnapshot.objects.filter(
        asin=asin_obj, date__range=(start, end)
    ).aggregate(avg_bsr=Avg("bsr_rank"))

    avg = result.get("avg_bsr")
    return int(round(avg)) if avg is not None else None


def _classify_trend(yoy_change: int, baseline_rank: int) -> str:
    """
    Label trend using percentage delta thresholds:
      improving  → rank dropped by > 10%  (lower = better)
      declining  → rank rose by > 10%
      stable     → within ±10%
    """
    if baseline_rank == 0:
        return "stable"
    pct = (yoy_change / baseline_rank) * 100
    if pct < -10:
        return "improving"
    if pct > 10:
        return "declining"
    return "stable"
