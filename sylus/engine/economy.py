import math
from typing import Dict, Any, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import Nation, Province, ResourceLedger, Building, ResourceMarketIndex, utc_now
from sylus.logging import get_logger

logger = get_logger(__name__)


async def process_economy_turn(session: AsyncSession) -> Dict[str, Any]:
    """Runs turn economic updates for all nations, production chains, upkeep, taxes, storage, and market index."""
    nations = (await session.execute(select(Nation))).scalars().all()
    buildings_cfg = config.get("buildings", {})
    resources_cfg = {r["name"]: r for r in config.get("resources.types", [])}
    govs_cfg = config.get("governments", {})
    policies_cfg = config.get("policies", {})

    opt_tax = float(config.get("balance.tax_rate_optimal", 0.25))
    base_pop_inc = float(config.get("balance.base_population_income", 10.0))
    pop_growth_rate = float(config.get("balance.base_population_growth_rate", 0.01))
    base_storage_cap = float(config.get("balance.base_storage_cap", 10000.0))
    upkeep_prov = float(config.get("balance.upkeep_per_province", 100.0))
    upkeep_pop = float(config.get("balance.upkeep_per_pop", 0.01))

    score_w = config.get("balance.score_weights", {})
    w_pop = float(score_w.get("population", 0.001))
    w_prov = float(score_w.get("province", 100.0))
    w_bldg = float(score_w.get("building", 50.0))
    w_res = float(score_w.get("resource_value", 0.01))

    total_supply_turn: Dict[str, float] = {r: 0.0 for r in resources_cfg.keys()}
    total_demand_turn: Dict[str, float] = {r: 0.0 for r in resources_cfg.keys()}

    for nation in nations:
        # 1. Update policy cooldowns
        cds = dict(nation.policy_cooldowns or {})
        updated_cds = {k: max(0, v - 1) for k, v in cds.items() if v > 0}
        nation.policy_cooldowns = updated_cds

        # Fetch nation provinces and buildings
        provinces = (
            await session.execute(select(Province).where(Province.nation_id == nation.id))
        ).scalars().all()
        buildings = (
            await session.execute(select(Building).where(Building.nation_id == nation.id))
        ).scalars().all()
        res_ledgers = (
            await session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == nation.id))
        ).scalars().all()
        ledger_map = {r.resource_type: r for r in res_ledgers}

        # 2. Advance building construction
        active_buildings: List[Building] = []
        for b in buildings:
            if b.turns_remaining > 0:
                b.turns_remaining -= 1
            if b.turns_remaining == 0:
                active_buildings.append(b)

        # 3. Calculate government & policy modifiers
        gov_info = govs_cfg.get(nation.government_type, {})
        gov_happy_mod = float(gov_info.get("happiness_modifier", 0.0))
        gov_tax_eff = float(gov_info.get("tax_efficiency", 1.0))
        gov_comm_bonus = float(gov_info.get("commerce_bonus", 0.0))

        prod_mult = 1.0
        comm_mult = 1.0 + gov_comm_bonus
        policy_happy_bonus = 0.0

        for pol_key in (nation.active_policies or {}):
            pol_data = policies_cfg.get(pol_key, {}).get("effects", {})
            prod_mult *= float(pol_data.get("production_multiplier", 1.0))
            comm_mult *= float(pol_data.get("commerce_multiplier", 1.0))
            policy_happy_bonus += float(pol_data.get("happiness_bonus", 0.0))

        # 4. Population growth & Happiness (Laffer curve tax effect)
        tax_diff = abs(nation.tax_rate - opt_tax)
        tax_happy_penalty = (tax_diff / opt_tax) ** 2 if opt_tax > 0 else 0.0
        target_happiness = max(0.0, min(1.0, 0.80 + gov_happy_mod + policy_happy_bonus - tax_happy_penalty * 0.4))
        nation.happiness = round(0.8 * nation.happiness + 0.2 * target_happiness, 3)

        pop_growth = int(nation.population * pop_growth_rate * nation.happiness)
        nation.population += pop_growth
        if provinces:
            pop_per_prov = pop_growth // len(provinces)
            for p in provinces:
                p.population += pop_per_prov

        # 5. Laffer-style Tax Revenue
        # Revenue = TaxRate * Pop * BaseIncome * TaxEff * (1 - (TaxRate / (2 * OptTax)))
        laffer_factor = max(0.0, 1.0 - (nation.tax_rate / (2.0 * opt_tax if opt_tax > 0 else 1.0)))
        tax_income = nation.population * base_pop_inc * nation.tax_rate * gov_tax_eff * laffer_factor

        # 6. Building Production & Input Consumption
        net_change: Dict[str, float] = {r: 0.0 for r in resources_cfg.keys()}
        net_change["money"] += tax_income

        for b in active_buildings:
            b_data = buildings_cfg.get(b.building_type, {})
            b_inputs = b_data.get("inputs", {})
            b_outputs = b_data.get("outputs", {})
            b_upkeep = b_data.get("upkeep", {})
            b_terrain_bonus = b_data.get("terrain_bonus", {})

            # Determine terrain modifier
            prov = next((p for p in provinces if p.id == b.province_id), None)
            terrain_mult = 1.0
            if prov and prov.terrain in b_terrain_bonus:
                terrain_mult = float(b_terrain_bonus[prov.terrain])

            # Check input fulfillment ratio
            fulfillment = 1.0
            for in_res, in_amt in b_inputs.items():
                req = float(in_amt) * b.level
                total_demand_turn[in_res] = total_demand_turn.get(in_res, 0.0) + req
                curr_bal = ledger_map.get(in_res).balance if in_res in ledger_map else 0.0
                if curr_bal < req:
                    avail_ratio = curr_bal / req if req > 0 else 0.0
                    fulfillment = min(fulfillment, avail_ratio)

            # Deduct inputs
            for in_res, in_amt in b_inputs.items():
                deduct = float(in_amt) * b.level * fulfillment
                net_change[in_res] -= deduct

            # Add outputs
            for out_res, out_amt in b_outputs.items():
                gen = float(out_amt) * b.level * terrain_mult * prod_mult * fulfillment
                if out_res == "money":
                    gen *= comm_mult
                net_change[out_res] += gen
                total_supply_turn[out_res] = total_supply_turn.get(out_res, 0.0) + gen

            # Deduct building upkeep
            for up_res, up_amt in b_upkeep.items():
                net_change[up_res] -= float(up_amt) * b.level

        # Province & Pop Upkeep
        total_upkeep_money = (len(provinces) * upkeep_prov) + (nation.population * upkeep_pop)
        net_change["money"] -= total_upkeep_money

        # Apply net changes to ledgers
        for r_type, delta in net_change.items():
            if r_type not in ledger_map:
                ledger = ResourceLedger(nation_id=nation.id, resource_type=r_type, balance=0.0)
                session.add(ledger)
                ledger_map[r_type] = ledger

            ledger_map[r_type].balance = max(0.0, ledger_map[r_type].balance + delta)

        # 7. Storage limits & Spoilage
        extra_storage = sum(
            buildings_cfg.get(b.building_type, {}).get("storage_bonus", 0)
            for b in active_buildings
        )
        total_storage_cap = base_storage_cap + extra_storage

        resource_val_sum = 0.0
        for r_type, ledger in ledger_map.items():
            r_cfg = resources_cfg.get(r_type, {})
            if r_cfg.get("is_storable", True) and r_type != "money":
                if ledger.balance > total_storage_cap:
                    ledger.balance = total_storage_cap
                spoil_rate = float(r_cfg.get("spoilage_rate", 0.0))
                ledger.balance *= (1.0 - spoil_rate)

            base_p = float(r_cfg.get("base_price", 1.0))
            resource_val_sum += ledger.balance * base_p

        # 8. Nation Score Calculation
        nation.score = (
            (nation.population * w_pop)
            + (len(provinces) * w_prov)
            + (len(active_buildings) * w_bldg)
            + (resource_val_sum * w_res)
        )

    # 9. Inflation / Market Price Index Update
    await _update_market_prices(session, total_supply_turn, total_demand_turn, resources_cfg)

    logger.info("Processed economy turn successfully", total_nations=len(nations))
    return {"total_nations": len(nations)}


async def _update_market_prices(
    session: AsyncSession,
    supply_turn: Dict[str, float],
    demand_turn: Dict[str, float],
    resources_cfg: Dict[str, Any],
) -> None:
    sens = float(config.get("balance.market.price_sensitivity", 0.05))
    min_m = float(config.get("balance.market.min_price_multiplier", 0.2))
    max_m = float(config.get("balance.market.max_price_multiplier", 5.0))

    for r_type, r_info in resources_cfg.items():
        base_p = float(r_info.get("base_price", 10.0))
        sup = supply_turn.get(r_type, 0.0)
        dem = demand_turn.get(r_type, 0.0)

        market_item = (
            await session.execute(
                select(ResourceMarketIndex).where(ResourceMarketIndex.resource_type == r_type)
            )
        ).scalar_one_or_none()

        if not market_item:
            market_item = ResourceMarketIndex(
                resource_type=r_type,
                current_price=base_p,
                supply_turn=sup,
                demand_turn=dem,
            )
            session.add(market_item)
        else:
            market_item.supply_turn = sup
            market_item.demand_turn = dem

            # Price adjustment formula based on supply vs demand
            if dem > sup:
                ratio = (dem - sup) / (sup + 1.0)
                market_item.current_price *= (1.0 + sens * min(ratio, 2.0))
            elif sup > dem:
                ratio = (sup - dem) / (dem + 1.0)
                market_item.current_price *= (1.0 - sens * min(ratio, 2.0))

            # Clamp price
            market_item.current_price = max(base_p * min_m, min(base_p * max_m, market_item.current_price))
