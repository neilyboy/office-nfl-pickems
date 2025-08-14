from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Week(Base):
    __tablename__ = "weeks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), index=True)
    week_number: Mapped[int] = mapped_column(Integer, index=True)
    # ESPN semantics: 1=Preseason, 2=Regular, 3=Postseason
    season_type: Mapped[int] = mapped_column(Integer, index=True, default=2)
    first_kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    season: Mapped["Season"] = relationship(back_populates="weeks")
    games: Mapped[list["Game"]] = relationship(back_populates="week", cascade="all, delete-orphan")

    def is_locked(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        fk = self.first_kickoff_at
        # SQLite may return naive datetimes even when timezone=True; treat them as UTC
        if fk.tzinfo is None or fk.tzinfo.utcoffset(fk) is None:
            fk = fk.replace(tzinfo=timezone.utc)
        return now >= fk

    @property
    def season_type_name(self) -> str:
        mapping = {1: "Preseason", 2: "Regular", 3: "Postseason"}
        st = getattr(self, "season_type", None)
        if st is None:
            st = 2
        return mapping.get(int(st), f"Type {st}")
