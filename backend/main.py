"""FastAPI entrypoint for the template.

Run locally:   uvicorn backend.main:app --reload
On Render:     uvicorn backend.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .auth import provision_user
from .config import settings
from .db import Base, SessionLocal, engine, get_db
from .models import StrategyProfile  # noqa: F401
from .routes import router
from .starter_profile import STARTER_PROFILE

app = FastAPI(title="Funding Fit Scorer (template)")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax", https_only=False)


def seed_if_needed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(StrategyProfile).count() == 0:
            sp = STARTER_PROFILE
            db.add(StrategyProfile(
                version=sp["version"], name=sp["name"], profile_doc=sp["profile_doc"],
                dimensions=sp["dimensions"], hard_filters=sp["hard_filters"],
                thresholds=sp["thresholds"], tiers=sp["tiers"], is_active=True,
                is_placeholder=True, created_by="system", approved_by="system"))
            db.commit()
    finally:
        db.close()


@app.on_event("startup")
def _startup():
    seed_if_needed()


if settings.use_google_oauth:
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(name="google", client_id=settings.google_client_id,
                   client_secret=settings.google_client_secret,
                   server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                   client_kwargs={"scope": "openid email profile"})

    @app.get("/api/login/google")
    async def login_google(request: Request):
        return await oauth.google.authorize_redirect(
            request, settings.base_url.rstrip("/") + "/api/auth/google/callback")

    @app.get("/api/auth/google/callback")
    async def google_callback(request: Request, db: Session = Depends(get_db)):
        token = await oauth.google.authorize_access_token(request)
        info = token.get("userinfo") or {}
        try:
            user = provision_user(db, info.get("email", ""), info.get("name", ""))
        except Exception:  # noqa: BLE001
            return RedirectResponse("/?error=not_allowed")
        request.session["user_id"] = user.id
        return RedirectResponse("/")


app.include_router(router)

_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
