from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.templates import templates
from app.db.session import get_db
from app.deps.auth import get_current_user

router = APIRouter()


@router.get("/history", response_class=HTMLResponse)
def history_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    ctx = {"request": request, "title": "History", "current_user": user}
    return templates.TemplateResponse("history.html", ctx)
