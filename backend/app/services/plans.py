"""
Subscription tier logic — single source of truth for plan limits and quota.

Tiers (see roadmap item #3):
  free          — Découverte : 3 quote sends, lifetime
  plus          — Plus       : 15 quote sends / calendar month  (€9/mo)
  conciergerie  — Conciergerie: unlimited                       (€19/mo)
"""

from datetime import datetime, timezone

from app import db

# window: "lifetime" | "month" | None (unlimited).  limit: int | None
PLAN_LIMITS: dict[str, tuple[str | None, int | None]] = {
    "free": ("lifetime", 3),
    "plus": ("month", 15),
    "conciergerie": (None, None),
}


def _month_start_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def effective_plan(user: dict) -> str:
    """The plan actually in force.

    A paid plan stays effective while its subscription is active, or while a
    cancelled subscription is still inside its paid period (plan_period_end in
    the future). Otherwise the user falls back to free.
    """
    plan = (user.get("plan") or "free").strip().lower()
    if plan == "free" or plan not in PLAN_LIMITS:
        return "free"

    status = (user.get("plan_status") or "").strip().lower()
    if status in ("active", "trialing"):
        return plan

    # Not active — honour any remaining paid period before downgrading.
    period_end = user.get("plan_period_end")
    if period_end:
        try:
            if datetime.fromisoformat(period_end) > datetime.now(timezone.utc):
                return plan
        except ValueError:
            pass
    return "free"


def quota_status(email: str, plan: str) -> dict:
    """{used, limit, remaining, window} for the given plan. Unlimited → limit None."""
    window, limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    if limit is None:
        return {"used": 0, "limit": None, "remaining": None, "window": None}
    since = _month_start_iso() if window == "month" else None
    used = db.count_quote_sends(email, since)
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "window": window,
    }
