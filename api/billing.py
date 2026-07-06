"""Stripe: checkout, portal, webhook. All endpoints 503 until Stripe env is set."""
import os

from fastapi import APIRouter, Depends, HTTPException, Request

import db
from auth import current_user

router = APIRouter()


def _stripe():
    if not os.environ.get("STRIPE_SECRET_KEY"):
        raise HTTPException(503, {"code": "billing_disabled", "message": "billing not configured"})
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def _customer_id(stripe, user) -> str:
    if user["stripe_customer_id"]:
        return user["stripe_customer_id"]
    cust = stripe.Customer.create(email=user["email"])
    db.ex("UPDATE users SET stripe_customer_id=? WHERE id=?", (cust.id, user["id"]))
    return cust.id


@router.post("/billing/checkout")
def checkout(user=Depends(current_user)):
    stripe = _stripe()
    front = os.environ.get("FRONTEND_ORIGIN", "")
    session = stripe.checkout.Session.create(
        customer=_customer_id(stripe, user),
        mode="subscription",
        line_items=[{"price": os.environ["STRIPE_PRICE_ID"], "quantity": 1}],
        success_url=f"{front}/account?upgraded=1",
        cancel_url=f"{front}/account",
    )
    return {"url": session.url}


@router.post("/billing/portal")
def portal(user=Depends(current_user)):
    stripe = _stripe()
    if not user["stripe_customer_id"]:
        raise HTTPException(400, {"code": "no_customer", "message": "no billing account yet"})
    session = stripe.billing_portal.Session.create(
        customer=user["stripe_customer_id"],
        return_url=f"{os.environ.get('FRONTEND_ORIGIN', '')}/account",
    )
    return {"url": session.url}


@router.post("/webhooks/stripe")
async def webhook(request: Request):
    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(
            await request.body(),
            request.headers.get("stripe-signature", ""),
            os.environ["STRIPE_WEBHOOK_SECRET"],
        )
    except Exception:
        raise HTTPException(400, {"code": "bad_signature", "message": "invalid webhook signature"})
    obj = event["data"]["object"]
    if event["type"] == "checkout.session.completed":
        db.ex("UPDATE users SET plan='pro', payment_failed=0 WHERE stripe_customer_id=?",
              (obj["customer"],))
    elif event["type"] == "customer.subscription.deleted":
        db.ex("UPDATE users SET plan='free' WHERE stripe_customer_id=?", (obj["customer"],))
    elif event["type"] == "invoice.payment_failed":
        db.ex("UPDATE users SET payment_failed=1 WHERE stripe_customer_id=?", (obj["customer"],))
    return {"ok": True}
