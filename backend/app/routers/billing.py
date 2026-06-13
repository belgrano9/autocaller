"""
Stripe subscription billing — Checkout, customer portal, and webhook.

Monthly subscriptions (mode="subscription"). Two paid tiers map to two
recurring Price IDs configured in .env:
  plus          → STRIPE_PRICE_PLUS         (€9/mo)
  conciergerie  → STRIPE_PRICE_CONCIERGERIE (€19/mo)

The webhook is the source of truth for a user's plan: it keys off the Stripe
customer id and is safe to replay (idempotent upserts).
"""

from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from app import db
from app.config import settings
from app.routers.auth import authenticate_session

router = APIRouter(prefix="/billing", tags=["billing"])

stripe.api_key = settings.stripe_secret_key


def _price_to_plan() -> dict[str, str]:
    return {
        settings.stripe_price_plus: "plus",
        settings.stripe_price_conciergerie: "conciergerie",
    }


def _plan_to_price() -> dict[str, str]:
    return {
        "plus": settings.stripe_price_plus,
        "conciergerie": settings.stripe_price_conciergerie,
    }


class CheckoutRequest(BaseModel):
    plan: str  # "plus" | "conciergerie"


def _ensure_customer(user: dict) -> str:
    """Returns the user's Stripe customer id, creating + persisting one if absent."""
    customer_id = user.get("stripe_customer_id")
    if customer_id:
        return customer_id
    customer = stripe.Customer.create(
        email=user["email"], name=user.get("name") or None
    )
    db.set_billing(user["email"], stripe_customer_id=customer.id)
    return customer.id


@router.post("/checkout")
def create_checkout(req: CheckoutRequest, user: dict = Depends(authenticate_session)):
    """Creates a subscription Checkout session; returns the hosted-page URL."""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing is not configured")
    price_id = _plan_to_price().get(req.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Unknown plan")

    customer_id = _ensure_customer(user)
    base = settings.app_base_url.rstrip("/")
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=user["email"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base}/dashboard?checkout=success",
        cancel_url=f"{base}/dashboard?checkout=cancel",
    )
    return {"url": session.url}


@router.post("/portal")
def create_portal(user: dict = Depends(authenticate_session)):
    """Creates a Stripe billing-portal session (manage/cancel)."""
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="No subscription to manage")
    base = settings.app_base_url.rstrip("/")
    session = stripe.billing_portal.Session.create(
        customer=customer_id, return_url=f"{base}/dashboard"
    )
    return {"url": session.url}


def _apply_subscription(sub: dict):
    """Updates a user's plan from a Stripe Subscription object (keyed by customer)."""
    customer_id = sub.get("customer")
    user = db.get_user_by_stripe_customer(customer_id) if customer_id else None
    if not user:
        logger.warning("Webhook: no user for stripe customer {}", customer_id)
        return

    status = sub.get("status")
    items = (sub.get("items") or {}).get("data") or []
    price_id = items[0]["price"]["id"] if items else None
    plan = _price_to_plan().get(price_id, "free")

    # current_period_end moved from the Subscription top level onto the items in
    # recent Stripe API versions (basil); read the item first, fall back to top.
    period_end = (items[0].get("current_period_end") if items else None) \
        or sub.get("current_period_end")
    period_end_iso = (
        datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()
        if period_end
        else None
    )

    db.set_billing(
        user["email"],
        source="subscription",
        plan=plan if status in ("active", "trialing") else user.get("plan") or "free",
        plan_status=status,
        plan_period_end=period_end_iso,
        stripe_subscription_id=sub.get("id"),
    )
    logger.info("Webhook: {} → plan={} status={}", user["email"], plan, status)


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Verifies the Stripe signature against the RAW body, then applies the event."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig, settings.stripe_webhook_secret
        )
    except Exception as exc:
        logger.error("Stripe webhook signature verification failed: {}", exc)
        raise HTTPException(status_code=400, detail="Invalid signature")

    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        sub_id = obj.get("subscription")
        if sub_id:
            _apply_subscription(stripe.Subscription.retrieve(sub_id))
    elif etype in ("customer.subscription.created", "customer.subscription.updated"):
        _apply_subscription(obj)
    elif etype == "customer.subscription.deleted":
        user = db.get_user_by_stripe_customer(obj.get("customer"))
        if user:
            db.set_billing(
                user["email"], source="subscription_deleted",
                plan="free", plan_status="canceled",
                stripe_subscription_id=None,
            )
            logger.info("Webhook: {} subscription canceled → free", user["email"])

    return {"received": True}
