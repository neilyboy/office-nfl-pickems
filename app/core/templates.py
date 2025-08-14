from __future__ import annotations

import hashlib
from fastapi.templating import Jinja2Templates
from urllib.parse import quote

from app.core.config import TEMPLATES_DIR, STATIC_DIR, get_settings

templates = Jinja2Templates(directory=TEMPLATES_DIR.as_posix())

def default_avatar(user) -> str:
    """Return deterministic default avatar path from a small icon set.

    Picks one of 6 SVGs under /static/avatars/defaults/ball{1-6}.svg based on
    username hash (falling back to id if needed).
    """
    key_src = getattr(user, "username", None) or str(getattr(user, "id", ""))
    key = key_src.encode("utf-8")
    idx = int(hashlib.sha256(key).hexdigest(), 16) % 6 + 1
    return f"/static/avatars/defaults/ball{idx}.svg"

templates.env.globals["default_avatar"] = default_avatar

def team_logo(team) -> str:
    """Return logo URL for a team, falling back to a generated SVG data URL.

    The fallback is a small rounded badge with the team's abbreviation.
    """
    if not team:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="100%" height="100%" rx="6" fill="#0f172a"/></svg>'
        return f"data:image/svg+xml;utf8,{quote(svg)}"
    path = getattr(team, "logo_path", None)
    if path:
        # If path points to local static, ensure file exists; otherwise fall back
        try:
            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                fs_path = (STATIC_DIR / rel)
                if not fs_path.exists():
                    raise FileNotFoundError
            return path
        except Exception:
            pass
    abbr = getattr(team, "abbr", "?")
    # Simple dark badge with abbr text
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">
  <rect width="100%" height="100%" rx="6" fill="#0f172a" stroke="#334155"/>
  <text x="50%" y="55%" text-anchor="middle" font-family="Inter,Arial" font-size="14" fill="#e2e8f0">{abbr}</text>
</svg>'''
    return f"data:image/svg+xml;utf8,{quote(svg)}"

templates.env.globals["team_logo"] = team_logo

# Environment flag for template conditionals
IS_DEV = get_settings().ENV == "development"
templates.env.globals["IS_DEV"] = IS_DEV

# In development, auto-reload templates and clear cache for faster iteration
if IS_DEV:
    try:
        templates.env.auto_reload = True
        templates.env.cache = {}
    except Exception:
        pass
