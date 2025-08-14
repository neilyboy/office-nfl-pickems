from __future__ import annotations

from typing import List, Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    location: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    abbr: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    alt_abbrs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string of alt abbreviations
    logo_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    def alt_abbreviations(self) -> List[str]:
        import json

        if not self.alt_abbrs:
            return []
        try:
            return list(json.loads(self.alt_abbrs))
        except Exception:
            return []
