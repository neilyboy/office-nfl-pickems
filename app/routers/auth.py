from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.templates import templates
from app.core.security import verify_password, hash_password
from app.db.session import get_db
from app.models import User
from app.deps.auth import get_current_user, login_user, logout_user

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "title": "Login"})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        # Simple feedback via query param
        return RedirectResponse("/login?err=1", status_code=302)

    # If password change is required, send user to change-password first
    if user.must_change_password:
        resp = RedirectResponse("/profile/change-password?force=1", status_code=302)
        login_user(resp, user)
        return resp

    resp = RedirectResponse("/dashboard", status_code=302)
    login_user(resp, user)
    return resp


@router.get("/logout")
def logout(request: Request):
    resp = RedirectResponse("/login", status_code=302)
    logout_user(resp)
    return resp


@router.get("/setup-admin", response_class=HTMLResponse)
def setup_admin_page(request: Request, db: Session = Depends(get_db)):
    # If any user exists, redirect
    if db.query(User.id).first():
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("setup_admin.html", {"request": request, "title": "First-time Setup"})


@router.post("/setup-admin")
def setup_admin_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    first_name: str = Form(""),
    last_name: str = Form(""),
    db: Session = Depends(get_db),
):
    # If any user exists, abort
    if db.query(User.id).first():
        return RedirectResponse("/dashboard", status_code=302)

    user = User(
        username=username.strip(),
        password_hash=hash_password(password),
        first_name=first_name.strip() or "Admin",
        last_name=last_name.strip(),
        is_admin=True,
        must_change_password=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    resp = RedirectResponse("/dashboard", status_code=302)
    login_user(resp, user)
    return resp
