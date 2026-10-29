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
    crime: Mapped[float] = mapped_column(Float, default=0.10, nullable=False)
    health: Mapped[float] = mapped_column(Float, default=0.80, nullable=False)
    education: Mapped[float] = mapped_column(Float, default=0.50, nullable=False)
    pollution: Mapped[float] = mapped_column(Float, default=0.05, nullable=False)
    corruption: Mapped[float] = mapped_column(Float, default=0.10, nullable=False)
    war_support: Mapped[float] = mapped_column(Float, default=0.70, nullable=False)
    unrest_level: Mapped[str] = mapped_column(String(50), default="normal", nullable=False)
    workers: Mapped[int] = mapped_column(Integer, default=7000, nullable=False)
    soldiers: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    unemployed: Mapped[int] = mapped_column(Integer, default=2500, nullable=False)
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

class TradeOffer(Base):
    __tablename__ = "trade_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    receiver_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=True, index=True)
    offer_type: Mapped[str] = mapped_column(String(20), default="direct", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    original_offer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("trade_offers.id", ondelete="SET NULL"), nullable=True)
    expires_at_turn: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at_turn: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    asset_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    asset_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    total_quantity: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    filled_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    items: Mapped[list["TradeItem"]] = relationship("TradeItem", back_populates="trade_offer", cascade="all, delete-orphan")
    escrow_holds: Mapped[list["EscrowHold"]] = relationship("EscrowHold", back_populates="trade_offer", cascade="all, delete-orphan")

class TradeItem(Base):
    __tablename__ = "trade_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_offer_id: Mapped[int] = mapped_column(Integer, ForeignKey("trade_offers.id", ondelete="CASCADE"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    trade_offer: Mapped["TradeOffer"] = relationship("TradeOffer", back_populates="items")

class EscrowHold(Base):
    __tablename__ = "escrow_holds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_offer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("trade_offers.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True, index=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="locked", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    trade_offer: Mapped[Optional["TradeOffer"]] = relationship("TradeOffer", back_populates="escrow_holds")
    contract: Mapped[Optional["Contract"]] = relationship("Contract", back_populates="escrow_holds")

class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

class NationReputation(Base):
    __tablename__ = "nation_reputations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    contracts_fulfilled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contracts_breached: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_signatures", nullable=False)
    duration_turns: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    start_turn: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_turn: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    plain_language_summary: Mapped[str] = mapped_column(Text, nullable=False)
    stated_penalty_type: Mapped[str] = mapped_column(String(50), default="fine", nullable=False)
    stated_penalty_details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    appeal_window_turns: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    appeal_ends_at_turn: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_immutable: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    signatories: Mapped[list["ContractSignatory"]] = relationship("ContractSignatory", back_populates="contract", cascade="all, delete-orphan")
    obligations: Mapped[list["ContractObligation"]] = relationship("ContractObligation", back_populates="contract", cascade="all, delete-orphan")
    escrow_holds: Mapped[list["EscrowHold"]] = relationship("EscrowHold", back_populates="contract", cascade="all, delete-orphan")
    appeals: Mapped[list["ContractAppeal"]] = relationship("ContractAppeal", back_populates="contract", cascade="all, delete-orphan")

class ContractSignatory(Base):
    __tablename__ = "contract_signatories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(50), default="party", nullable=False)
    signed: Mapped[bool] = mapped_column(default=False, nullable=False)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    contract: Mapped["Contract"] = relationship("Contract", back_populates="signatories")

class ContractObligation(Base):
    __tablename__ = "contract_obligations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    payer_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    payee_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    obligation_type: Mapped[str] = mapped_column(String(30), default="recurring_per_turn", nullable=False)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    last_executed_turn: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    contract: Mapped["Contract"] = relationship("Contract", back_populates="obligations")

class ContractAppeal(Base):
    __tablename__ = "contract_appeals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    appellant_nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    appeal_turn: Mapped[int] = mapped_column(Integer, nullable=False)
    admin_override_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    contract: Mapped["Contract"] = relationship("Contract", back_populates="appeals")

class DisasterZone(Base):
    __tablename__ = "disaster_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("provinces.id", ondelete="CASCADE"), nullable=False, index=True)
    nation_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=True, index=True)
    disaster_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    turns_remaining: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at_turn: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

class UnitDesign(Base):
    __tablename__ = "unit_designs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    production_cost: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    upkeep: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    build_time: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    nation: Mapped["Nation"] = relationship("Nation", foreign_keys=[nation_id])

class NationEvent(Base):
    __tablename__ = "nation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    choices: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    chosen_option: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at_turn: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

class MilitaryQueue(Base):
    __tablename__ = "military_queues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("provinces.id", ondelete="CASCADE"), nullable=False, index=True)
    design_id: Mapped[int] = mapped_column(Integer, ForeignKey("unit_designs.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    turns_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    facility_type: Mapped[str] = mapped_column(String(50), nullable=False)  # factory, shipyard, airbase
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

class MilitaryFormation(Base):
    __tablename__ = "military_formations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("provinces.id", ondelete="CASCADE"), nullable=False, index=True)
    design_id: Mapped[int] = mapped_column(Integer, ForeignKey("unit_designs.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    experience: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    morale: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    fuel_status: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    ammo_status: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

class SpyIntel(Base):
    __tablename__ = "spy_intel"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spy_nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    target_nation_id: Mapped[int] = mapped_column(Integer, ForeignKey("nations.id", ondelete="CASCADE"), nullable=False, index=True)
    intel_level: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 0.0 to 1.0
    expires_at_turn: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
