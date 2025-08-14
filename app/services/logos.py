from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

from sqlalchemy.orm import Session

from app.core.config import STATIC_DIR
from app.models import Team

LOGOS_DIR = STATIC_DIR / "logos"

SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#111827"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" rx="10" fill="url(#g)" stroke="#334155"/>
  <text x="50%" y="56%" text-anchor="middle" font-family="Inter,Arial" font-size="26" font-weight="700" fill="#e2e8f0">{abbr}</text>
</svg>"""


def generate_offline_logos(db: Session) -> Tuple[int, int]:
    """Generate SVG logo files for all teams in DB.

    Returns (created, skipped) counts.
    """
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    created = 0
    skipped = 0

    teams: Iterable[Team] = db.query(Team).all()
    for t in teams:
        abbr = (t.abbr or "").upper()
        if not abbr:
            continue
        filename = LOGOS_DIR / f"{abbr}.svg"
        if filename.exists():
            skipped += 1
            continue
        svg = SVG_TEMPLATE.format(abbr=abbr)
        filename.write_text(svg, encoding="utf-8")
        created += 1
    return created, skipped
