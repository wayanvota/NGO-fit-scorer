"""Authentication: domain-restricted sessions (Google OAuth in prod, dev login
locally). A user is admitted only if their email domain is in
ALLOWED_EMAIL_DOMAINS. Emails in INITIAL_ADMIN_EMAILS become admin.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User


class AuthError(HTTPException):
    def __init__(self, detail: str, status_code: int = 401):
        super().__init__(status_code=status_code, detail=detail)


def domain_allowed(email: str) -> bool:
    email = (email or "").lower().strip()
    return "@" in email and email.split("@", 1)[1] in settings.allowed_domains


def provision_user(db: Session, email: str, name: str = "") -> User:
    email = email.lower().strip()
    if not domain_allowed(email):
        raise AuthError(
            f"'{email}' is not on an allowed domain ({', '.join(settings.allowed_domains)}).", 403)
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        role = "admin" if email in settings.admin_emails else "staff"
        if role == "staff" and db.query(User).count() == 0 and not settings.admin_emails:
            role = "admin"
        user = User(email=email, name=name or email.split("@", 1)[0], role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif name and not user.name:
        user.name = name
        db.commit()
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.query(User).filter(User.id == uid).first()


def require_user(user: Optional[User] = Depends(current_user)) -> User:
    if user is None:
        raise AuthError("Sign in required.")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise AuthError("Admin access required.", status_code=403)
    return user
