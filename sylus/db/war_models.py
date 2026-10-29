from datetime import datetime
from typing import Optional, Any
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sylus.db.base import Base
from sylus.db.models import utc_now, Nation


class War(Base):
    __tablename__ = "wars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attacker_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    defender_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    casus_belli: Mapped[str] = mapped_column(String(50), default="none", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)
    attacker_ap: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    defender_ap: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    attacker_fatigue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    defender_fatigue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    weather: Mapped[str] = mapped_column(String(30), default="clear", nullable=False)
    season: Mapped[str] = mapped_column(String(30), default="spring", nullable=False)
    created_at_turn: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    ended_at_turn: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    beige_until_turn: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ceasefire_offered_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    attacker: Mapped["Nation"] = relationship("Nation", foreign_keys=[attacker_id])
    defender: Mapped["Nation"] = relationship("Nation", foreign_keys=[defender_id])
    logs: Mapped[list["WarLog"]] = relationship("WarLog", back_populates="war", cascade="all, delete-orphan")


class WarLog(Base):
    __tablename__ = "war_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    war_id: Mapped[int] = mapped_column(Integer, ForeignKey("wars.id", ondelete="CASCADE"), nullable=False, index=True)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    attacker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    defender_id: Mapped[int] = mapped_column(Integer, nullable=False)
    province_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    victory_tier: Mapped[str] = mapped_column(String(50), nullable=False)
    attacker_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    defender_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    roll_diff: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    casualties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    loot_resources: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    modifiers_applied: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    war: Mapped["War"] = relationship("War", back_populates="logs")
