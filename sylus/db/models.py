from datetime import datetime, timezone
from typing import Optional, Any, List
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, JSON, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sylus.db.base import Base

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class GlobalState(Base):
    __tablename__ = "global_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    turn_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_turn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_paused: Mapped[bool] = mapped_column(default=False, nullable=False)
    map_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    backup_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    snapshot_interval_turns: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

class Nation(Base):
    __tablename__ = "nations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    color: Mapped[Optional[str]] = mapped_column(String(20), default="#00FF00", nullable=True)
    leader_name: Mapped[str] = mapped_column(String(100), default="Leader", nullable=False)
    flag_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    government_type: Mapped[str] = mapped_column(String(50), default="republic", nullable=False)
    ideology: Mapped[str] = mapped_column(String(50), default="centrism", nullable=False)
    custom_leader_title: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    custom_govt_title: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.15, nullable=False)
    happiness: Mapped[float] = mapped_column(Float, default=0.80, nullable=False)
    population: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    active_policies: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    policy_cooldowns: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    provinces: Mapped[list["Province"]] = relationship("Province", back_populates="nation", cascade="all, delete-orphan")
    resources: Mapped[list["ResourceLedger"]] = relationship("ResourceLedger", back_populates="nation", cascade="all, delete-orphan")
    buildings: Mapped[list["Building"]] = relationship("Building", back_populates="nation", cascade="all, delete-orphan")
    unlocked_techs: Mapped[list["NationTech"]] = relationship("NationTech", back_populates="nation", cascade="all, delete-orphan")
    research_queue: Mapped[list["ResearchQueue"]] = relationship("ResearchQueue", back_populates="nation", cascade="all, delete-orphan")

class Province(Base):
    __tablename__ = "provinces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    nation_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("nations.id", ondelete="SET NULL"), nullable=True, index=True)
    terrain: Mapped[str] = mapped_column(String(50), default="plains", nullable=False)
    is_capital: Mapped[bool] = mapped_column(default=False, nullable=False)
    population: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    infrastructure: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    slot_cap: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    nation: Mapped[Optional["Nation"]] = relationship("Nation", back_populates="provinces")
    buildings: Mapped[list["Building"]] = relationship("Building", back_populates="province", cascade="all, delete-orphan")

class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("provinces.id", ondelete="CASCADE"), nullable=False, index=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    building_type: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    turns_remaining: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    province: Mapped["Province"] = relationship("Province", back_populates="buildings")
    nation: Mapped["Nation"] = relationship("Nation", back_populates="buildings")

class ResourceLedger(Base):
    __tablename__ = "resource_ledgers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    nation: Mapped["Nation"] = relationship("Nation", back_populates="resources")

class ResourceMarketIndex(Base):
    __tablename__ = "resource_market_index"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_type: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    supply_turn: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    demand_turn: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actor_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

class NationTech(Base):
    __tablename__ = "nation_techs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    tech_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    nation: Mapped["Nation"] = relationship("Nation", back_populates="unlocked_techs")

class ResearchQueue(Base):
    __tablename__ = "research_queues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    tech_id: Mapped[str] = mapped_column(String(100), nullable=False)
    allocated_rp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    target_rp: Mapped[float] = mapped_column(Float, nullable=False)
    queue_position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    nation: Mapped["Nation"] = relationship("Nation", back_populates="research_queue")

class TechLicense(Base):
    __tablename__ = "tech_licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    licensor_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    licensee_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    tech_id: Mapped[str] = mapped_column(String(100), nullable=False)
    royalty_per_turn: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    licensor: Mapped["Nation"] = relationship("Nation", foreign_keys=[licensor_id])
    licensee: Mapped["Nation"] = relationship("Nation", foreign_keys=[licensee_id])
