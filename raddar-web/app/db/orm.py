"""SQLAlchemy ORM models — the Postgres schema for events, users, and bookmarks.

Each row knows how to convert to its canonical pydantic shape so the rest of the app stays
backend-agnostic. Types are kept portable (no PG-only columns) for easy testing.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.users import User
from app.models import Category, CostTier, Event, SourceTier


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (
        # the discovery query filters on geofence (lat/lng) + temporal window
        Index("ix_events_geo", "lat", "lng"),
        Index("ix_events_start_time", "start_time"),
        Index("ix_events_expires_at", "expires_at"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    title_normalized: Mapped[str] = mapped_column(String, default="")
    category: Mapped[str] = mapped_column(String)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    cost_tier: Mapped[str] = mapped_column(String, default=CostTier.free.value)
    source_tier: Mapped[str] = mapped_column(String, default=SourceTier.api.value)
    source_name: Mapped[str] = mapped_column(String, default="")
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_event(self) -> Event:
        return Event(
            event_id=self.event_id,
            title=self.title,
            title_normalized=self.title_normalized,
            category=Category(self.category),
            start_time=self.start_time,
            end_time=self.end_time,
            lat=self.lat,
            lng=self.lng,
            cost_tier=CostTier(self.cost_tier),
            source_tier=SourceTier(self.source_tier),
            source_name=self.source_name,
            created_by=self.created_by,
            created_at=self.created_at,
            expires_at=self.expires_at,
        )

    @classmethod
    def from_event(cls, e: Event) -> "EventRow":
        return cls(
            event_id=e.event_id,
            title=e.title,
            title_normalized=e.title_normalized,
            category=e.category.value,
            start_time=e.start_time,
            end_time=e.end_time,
            lat=e.lat,
            lng=e.lng,
            cost_tier=e.cost_tier.value,
            source_tier=e.source_tier.value,
            source_name=e.source_name,
            created_by=e.created_by,
            created_at=e.created_at,
            expires_at=e.expires_at,
        )


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_user_identity"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_user(self) -> User:
        return User(
            id=self.id,
            provider=self.provider,
            subject=self.subject,
            email=self.email,
            name=self.name,
            created_at=self.created_at,
        )


class BookmarkRow(Base):
    __tablename__ = "bookmarks"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
