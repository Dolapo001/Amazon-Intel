"""
Revenue estimation engine.

Primary path:  Trained XGBoost regression model per category.
Fallback path: Category-calibrated BSR formula (BSR-based heuristic).

build_revenue_payload(asin_obj) → dict matching RevenueEstimateSerializer
"""
import logging
import math
import pickle
from pathlib import Path
from datetime import date
from typing import Optional

import numpy as np
from django.conf import settings
from apps.products.models import ASIN, BSRSnapshot, RevenueEstimate

logger = logging.getLogger(__name__)

MODEL_DIR = Path(settings.MODEL_STORAGE_PATH)


# ── Public interface ──────────────────────────────────────────────────────────

def build_revenue_payload(asin_obj: ASIN, force_recompute: bool = False) -> dict:
    """
    Return a revenue dict:
      { monthly, yoyChange, confidence, seasonalityAdjusted }

    Attempts ML model first; degrades to formula if model unavailable.
    """
    # Try to use cached RevenueEstimate record from DB
    if not force_recompute:
        try:
            estimate = asin_obj.revenue_estimate
            # If we have a valid revenue AND yoyChange isn't missing (if it could be computed), return it
            if estimate.monthly_revenue > 0 and estimate.yoy_change_pct is not None:
                return {
                    "monthly": float(estimate.monthly_revenue),
                    "yoyChange": estimate.yoy_change_pct,
                    "confidence": estimate.confidence,
                    "seasonalityAdjusted": estimate.seasonality_adjusted,
                }
        except RevenueEstimate.DoesNotExist:
            pass

    # Compute on-the-fly (only for freshly-ingested ASINs not yet modelled)
    monthly, confidence = _estimate_revenue(asin_obj)
    yoy = _compute_yoy_revenue_change(asin_obj)
    seasonality_adjusted = _apply_seasonality(asin_obj, monthly)

    # Persist so future requests are instant
    RevenueEstimate.objects.update_or_create(
        asin=asin_obj,
        defaults={
            "monthly_revenue": seasonality_adjusted,
            "yoy_change_pct": yoy,
            "confidence": confidence,
            "seasonality_adjusted": True,
        },
    )

    return {
        "monthly": round(seasonality_adjusted, 2),
        "yoyChange": yoy,
        "confidence": confidence,
        "seasonalityAdjusted": True,
    }


# ── ML model ──────────────────────────────────────────────────────────────────

def _load_model(category_id: Optional[str]):
    """Load the category-specific XGBoost model, falling back to global model."""
    paths_to_try = []
    if category_id:
        paths_to_try.append(MODEL_DIR / f"revenue_model_{category_id}.pkl")
    paths_to_try.append(MODEL_DIR / "revenue_model_global.pkl")

    for path in paths_to_try:
        if path.exists():
            try:
                with open(path, "rb") as f:
                    return pickle.load(f)
            except Exception as exc:
                logger.warning("model_load_failed", extra={"path": str(path), "error": str(exc)})
    return None


def _estimate_revenue(asin_obj: ASIN) -> tuple[float, float]:
    """
    Returns (monthly_revenue_usd, confidence_0_to_1).
    Uses ML model when available; falls back to BSR formula.
    """
    category_id = asin_obj.category.amazon_id if asin_obj.category else None
    model = _load_model(category_id)

    if model and asin_obj.current_bsr:
        features = _build_features(asin_obj)
        if features is not None:
            try:
                revenue = float(model.predict([features])[0])
                # XGBoost can expose feature importances for confidence proxy
                confidence = _model_confidence(model, features)
                return max(revenue, 0.0), confidence
            except Exception as exc:
                logger.warning("model_predict_failed", extra={"asin": asin_obj.asin, "error": str(exc)})

    # ── Fallback: calibrated BSR formula ────────────────────────────────
    return _formula_estimate(asin_obj)


def _build_features(asin_obj: ASIN) -> Optional[list]:
    """Assemble the feature vector expected by the XGBoost model."""
    if not asin_obj.current_bsr:
        return None

    # Historical BSR slope (linear trend over last 30 days)
    bsr_slope = _bsr_slope_30d(asin_obj)

    category_depth = 1  # root category by default
    seasonality_index = _current_seasonality_index(asin_obj)

    return [
        math.log1p(asin_obj.current_bsr),          # log-transform BSR
        float(asin_obj.current_price or 0),
        float(asin_obj.current_rating or 0),
        float(asin_obj.current_review_count or 0),
        bsr_slope,
        category_depth,
        seasonality_index,
    ]


def _formula_estimate(asin_obj: ASIN) -> tuple[float, float]:
    """
    BSR-to-revenue heuristic:
      sales_units = k / BSR  (k is category-calibrated constant)
      revenue = sales_units × price
    """
    if not asin_obj.current_bsr or not asin_obj.current_price:
        return 0.0, 0.0

    multiplier = 1.0
    if asin_obj.category:
        multiplier = asin_obj.category.bsr_revenue_multiplier

    k = 100_000 * multiplier
    units_per_month = k / asin_obj.current_bsr
    revenue = units_per_month * float(asin_obj.current_price)
    return revenue, 0.55   # lower confidence for formula path


def _model_confidence(model, features: list) -> float:
    """
    Proxy confidence from prediction interval width.
    For XGBoost we use the ntree_limit trick; real-world: use quantile regression.
    Falls back to 0.75 (mid-high) if not computable.
    """
    try:
        import xgboost as xgb
        dmat = xgb.DMatrix([features])
        pred_mean = float(model.predict(dmat)[0])
        # Crude variance proxy: coefficient of variation across trees
        preds = [float(model.predict(dmat, iteration_range=(0, t))[0]) for t in range(10, model.num_boosted_rounds, 10)]
        if len(preds) > 1:
            cv = np.std(preds) / (np.mean(preds) + 1e-6)
            return float(np.clip(1 - cv, 0.5, 0.98))
    except Exception:
        pass
    return 0.75


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bsr_slope_30d(asin_obj: ASIN) -> float:
    """Linear regression slope of BSR over last 30 days. Negative = improving."""
    from datetime import timedelta
    snapshots = list(
        BSRSnapshot.objects.filter(
            asin=asin_obj, date__gte=date.today() - timedelta(days=30)
        ).order_by("date").values_list("bsr_rank", flat=True)
    )
    if len(snapshots) < 3:
        return 0.0
    x = np.arange(len(snapshots), dtype=float)
    y = np.array(snapshots, dtype=float)
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def _current_seasonality_index(asin_obj: ASIN) -> float:
    """Return the category seasonality index for the current month (0–2 scale, 1.0 = average)."""
    if not asin_obj.category or not asin_obj.category.seasonality_indices:
        return 1.0
    indices = asin_obj.category.seasonality_indices
    current_month = date.today().month - 1   # 0-indexed
    if len(indices) == 12:
        return float(indices[current_month])
    return 1.0


def _apply_seasonality(asin_obj: ASIN, base_revenue: float) -> float:
    """Scale raw revenue estimate by current month's seasonality index."""
    index = _current_seasonality_index(asin_obj)
    return base_revenue * index


def _compute_yoy_revenue_change(asin_obj: ASIN) -> Optional[float]:
    """
    Estimate YoY revenue change from BSR rank shift.
    Uses best available historical baseline (365d -> 90d -> 30d -> oldest).
    """
    from .bsr import _get_best_baseline_rank
    
    current_bsr = asin_obj.current_bsr
    baseline_bsr = _get_best_baseline_rank(asin_obj)

    if not current_bsr or baseline_bsr is None:
        return None

    # Revenue ∝ 1/BSR → YoY revenue change ≈ (BSR_then / BSR_now - 1) × 100
    yoy_pct = (baseline_bsr / current_bsr - 1) * 100
    return round(yoy_pct, 1)
