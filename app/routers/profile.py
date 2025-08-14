from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.templates import templates
from app.core.security import hash_password
from app.db.session import get_db
from app.deps.auth import get_current_user
from app.models import User
from app.core.config import DATA_DIR

router = APIRouter()


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    return templates.TemplateResponse("profile.html", {"request": request, "title": "Profile", "current_user": user})


@router.post("/profile")
def profile_update(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    user.first_name = first_name.strip()
    user.last_name = last_name.strip()
    db.add(user)
    db.commit()

    return RedirectResponse("/profile", status_code=302)


@router.get("/profile/change-password", response_class=HTMLResponse)
def change_password_page(request: Request, force: int = 0, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "title": "Change Password", "current_user": user, "show_change_password": True, "force": force},
    )


@router.post("/profile/change-password")
def change_password_submit(
    request: Request,
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    user.password_hash = hash_password(password)
    user.must_change_password = False
    db.add(user)
    db.commit()

    # After changing password, take the user to the dashboard
    return RedirectResponse("/dashboard", status_code=302)


@router.post("/profile/avatar")
def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    # Validate content type
    allowed = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    if file.content_type not in allowed:
        return RedirectResponse("/profile?error=bad_file_type", status_code=302)

    # Import Pillow lazily to avoid breaking app if not yet installed
    try:
        from PIL import Image
    except Exception:
        return RedirectResponse("/profile?error=install_pillow", status_code=302)

    avatars_dir = DATA_DIR / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)

    # Process image: center-crop to square and resize to 256x256 PNG
    try:
        image = Image.open(file.file)
        image = image.convert("RGB")
        w, h = image.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        image = image.crop((left, top, left + side, top + side))
        image = image.resize((256, 256), Image.LANCZOS)

        filename = f"user{user.id}_{uuid.uuid4().hex}.png"
        dest_path = avatars_dir / filename
        image.save(dest_path.as_posix(), format="PNG", optimize=True)
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    # Remove old avatar if present
    old = user.avatar_path or ""
    if old.startswith("/avatars/"):
        try:
            old_path = avatars_dir / old.split("/avatars/")[1]
            if old_path.exists():
                old_path.unlink()
        except Exception:
            pass

    user.avatar_path = f"/avatars/{filename}"
    db.add(user)
    db.commit()

    return RedirectResponse("/profile?ok=avatar", status_code=302)


@router.post("/profile/avatar/delete")
def delete_avatar(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    avatars_dir = DATA_DIR / "avatars"
    old = user.avatar_path or ""
    if old.startswith("/avatars/"):
        try:
            old_path = avatars_dir / old.split("/avatars/")[1]
            if old_path.exists():
                old_path.unlink()
        except Exception:
            pass

    user.avatar_path = None
    db.add(user)
    db.commit()

    return RedirectResponse("/profile?ok=avatar_deleted", status_code=302)
