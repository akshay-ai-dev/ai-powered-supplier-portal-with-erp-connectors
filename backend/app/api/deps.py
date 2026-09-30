"""Shared API dependencies.

There is no real login in the prototype (SRS §3): the role picker sends the chosen
demo user's id in the `X-Portal-User` header on every request.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session

from app.db.session import get_session
from app.notifications.directory import User, get_user

SessionDep = Annotated[Session, Depends(get_session)]


def current_user(x_portal_user: Annotated[str | None, Header()] = None) -> User:
    if not x_portal_user:
        raise HTTPException(401, "Missing X-Portal-User header. Pick a role first.")
    user = get_user(x_portal_user)
    if user is None:
        raise HTTPException(401, f"Unknown user '{x_portal_user}'.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
