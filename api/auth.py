"""Auth: sessions (httpOnly cookie), magic links, Google OAuth code flow."""
import base64
import hashlib
import json
import os
import re
import secrets
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

import db

COOKIE = "genaudi_session"
SESSION_SECONDS = 30 * 86400
MAGIC_TTL = 900
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(prefix="/auth")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> int:
    return int(time.time())


def get_or_create_user(email: str, google_id: str | None = None) -> int:
    row = db.q1("SELECT id, google_id FROM users WHERE email=?", (email,))
    if row:
        if google_id and not row["google_id"]:
            db.ex("UPDATE users SET google_id=? WHERE id=?", (google_id, row["id"]))
        return row["id"]
    cur = db.ex(
        "INSERT INTO users(email, google_id, created_at) VALUES(?,?,?)",
        (email, google_id, _now()),
    )
    return cur.lastrowid


def create_session(resp: Response, user_id: int):
    token = secrets.token_urlsafe(32)
    db.ex(
        "INSERT INTO sessions VALUES(?,?,?)",
        (_hash(token), user_id, _now() + SESSION_SECONDS),
    )
    resp.set_cookie(
        COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
        secure=os.environ.get("COOKIE_SECURE", "0") == "1", samesite="lax",
    )


def current_user(request: Request):
    token = request.cookies.get(COOKIE)
    if token:
        row = db.q1(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>?",
            (_hash(token), _now()),
        )
        if row:
            return row
    raise HTTPException(401, {"code": "unauthorized", "message": "sign in required"})


def _user_json(u) -> dict:
    return {
        "email": u["email"], "plan": u["plan"],
        "chapters_converted": u["chapters_converted"],
        "payment_failed": bool(u["payment_failed"]),
    }


@router.get("/me")
def me(request: Request):
    try:
        return {"user": _user_json(current_user(request))}
    except HTTPException:
        return {"user": None}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        db.ex("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.post("/magic")
async def magic(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, {"code": "bad_email", "message": "invalid email"})
    token = secrets.token_urlsafe(32)
    db.ex("INSERT INTO magic_links VALUES(?,?,?)", (_hash(token), email, _now() + MAGIC_TTL))
    if os.environ.get("DEV_LOGIN") == "1":
        return {"ok": True, "dev_token": token}
    link = f"{os.environ.get('FRONTEND_ORIGIN', '')}/login?token={token}"
    async with httpx.AsyncClient() as cl:
        r = await cl.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
            json={
                "from": os.environ.get("MAIL_FROM", "genaudi <login@genaudi.app>"),
                "to": [email],
                "subject": "Your genaudi sign-in link",
                "text": f"Sign in to genaudi (valid 15 minutes):\n\n{link}\n",
            },
        )
    if r.status_code >= 400:
        raise HTTPException(502, {"code": "email_failed", "message": "could not send email"})
    return {"ok": True}


@router.post("/magic/verify")
def magic_verify(payload: dict, response: Response):
    token = payload.get("token") or ""
    row = db.q1(
        "SELECT email FROM magic_links WHERE token_hash=? AND expires_at>?",
        (_hash(token), _now()),
    )
    if not row:
        raise HTTPException(400, {"code": "bad_token", "message": "link expired or invalid"})
    db.ex("DELETE FROM magic_links WHERE token_hash=?", (_hash(token),))
    user_id = get_or_create_user(row["email"])
    create_session(response, user_id)
    return {"user": _user_json(db.q1("SELECT * FROM users WHERE id=?", (user_id,)))}


@router.post("/google")
async def google(payload: dict, response: Response):
    code = payload.get("code") or ""
    redirect_uri = payload.get("redirect_uri") or ""
    async with httpx.AsyncClient() as cl:
        r = await cl.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if r.status_code != 200:
        raise HTTPException(400, {"code": "oauth_failed", "message": "Google sign-in failed"})
    # id_token came straight from Google over TLS — payload is trusted, no signature check needed
    claims = json.loads(base64.urlsafe_b64decode(r.json()["id_token"].split(".")[1] + "=="))
    user_id = get_or_create_user(claims["email"].lower(), google_id=claims["sub"])
    create_session(response, user_id)
    return {"user": _user_json(db.q1("SELECT * FROM users WHERE id=?", (user_id,)))}
