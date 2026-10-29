from typing import Dict, Any, Optional
from sylus.config import config


def _get_war_config() -> Dict[str, Any]:
    return config.get("war.modifiers", {})


def calculate_terrain_modifier(action_type: str, terrain: str, role: str) -> float:
    cfg = _get_war_config().get("terrain", {}).get(terrain.lower(), {})
    mult = 1.0
    if role == "defender":
        mult += cfg.get("defender_bonus", 0.0)
    elif role == "attacker":
        mult += cfg.get("attacker_penalty", 0.0)
        mult += cfg.get("attacker_bonus", 0.0)

    if action_type == "ground_attack" and terrain.lower() == "jungle":
        mult += cfg.get("tank_penalty", 0.0)
    elif action_type == "ground_attack" and terrain.lower() == "urban" and role == "attacker":
        mult += cfg.get("infantry_bonus", 0.0)
    elif action_type == "naval_attack" and terrain.lower() == "coastal":
        mult += cfg.get("naval_support_bonus", 0.0)

    return max(0.1, mult)


def calculate_weather_modifier(action_type: str, weather: str) -> float:
    cfg = _get_war_config().get("weather", {}).get(weather.lower(), {})
    mult = cfg.get("multiplier", 1.0)
    if action_type == "air_strike":
        if cfg.get("air_grounded", False):
            return 0.0  # Aircraft grounded
        mult += cfg.get("air_penalty", 0.0)
        mult += cfg.get("accuracy_penalty", 0.0)
    elif action_type == "naval_attack":
        mult += cfg.get("naval_penalty", 0.0)
        mult += cfg.get("accuracy_penalty", 0.0)
    elif action_type == "ground_attack":
        mult += cfg.get("ground_speed_penalty", 0.0)

    return max(0.0, mult)


def calculate_season_modifier(action_type: str, season: str, terrain: str) -> float:
    cfg = _get_war_config().get("season", {}).get(season.lower(), {})
    mult = cfg.get("multiplier", 1.0)
    if season.lower() == "winter" and terrain.lower() == "arctic":
        mult += cfg.get("arctic_penalty", 0.0)
    elif season.lower() == "autumn" and terrain.lower() in ("plains", "forest"):
        # Autumn mud effect
        mult += cfg.get("mud_probability", 0.0) * -0.5
    return max(0.1, mult)


def calculate_supply_modifier(supply_level: float) -> float:
    cfg = _get_war_config().get("supply", {})
    unsupplied_penalty = cfg.get("unsupplied_power_penalty", -0.50)
    # supply_level from 0.0 to 1.0
    effective_penalty = (1.0 - max(0.0, min(1.0, supply_level))) * abs(unsupplied_penalty)
    return max(0.1, 1.0 - effective_penalty)


def calculate_morale_modifier(morale: float) -> float:
    cfg = _get_war_config().get("morale", {})
    base = cfg.get("base_morale", 100.0)
    scale = cfg.get("multiplier_scale", 0.005)
    diff = morale - base
    return max(0.1, 1.0 + (diff * scale))


def calculate_fatigue_modifier(fatigue: float) -> float:
    cfg = _get_war_config().get("fatigue", {})
    scale = cfg.get("fatigue_penalty_scale", 0.50)
    return max(0.1, 1.0 - (max(0.0, fatigue) * scale))


def calculate_experience_modifier(experience: float) -> float:
    cfg = _get_war_config().get("experience", {})
    base = cfg.get("base_experience", 10.0)
    scale = cfg.get("multiplier_scale", 0.002)
    diff = experience - base
    return max(0.1, 1.0 + (diff * scale))


def calculate_tech_gap_modifier(attacker_techs: int, defender_techs: int, role: str) -> float:
    cfg = _get_war_config().get("tech_gap", {})
    step = cfg.get("bonus_per_tech_difference", 0.05)
    cap = cfg.get("max_tech_gap_bonus", 0.30)
    diff = (attacker_techs - defender_techs) if role == "attacker" else (defender_techs - attacker_techs)
    bonus = max(-cap, min(cap, diff * step))
    return max(0.1, 1.0 + bonus)


def calculate_air_superiority_modifier(attacker_air_power: float, defender_air_power: float, role: str) -> float:
    cfg = _get_war_config().get("air_superiority", {})
    scale = cfg.get("air_ratio_bonus_scale", 0.25)
    total = attacker_air_power + defender_air_power
    if total <= 0:
        return 1.0
    ratio = (attacker_air_power / total) if role == "attacker" else (defender_air_power / total)
    bonus = (ratio - 0.5) * scale * 2.0
    return max(0.1, 1.0 + bonus)


def calculate_naval_control_modifier(attacker_naval_power: float, defender_naval_power: float, role: str) -> float:
    cfg = _get_war_config().get("naval_control", {})
    scale = cfg.get("naval_ratio_bonus_scale", 0.25)
    total = attacker_naval_power + defender_naval_power
    if total <= 0:
        return 1.0
    ratio = (attacker_naval_power / total) if role == "attacker" else (defender_naval_power / total)
    bonus = (ratio - 0.5) * scale * 2.0
    return max(0.1, 1.0 + bonus)


def calculate_radar_modifier(has_radar: bool, role: str) -> float:
    cfg = _get_war_config().get("radar", {})
    bonus = cfg.get("radar_detection_bonus", 0.15)
    return (1.0 + bonus) if has_radar else 1.0


def calculate_fortifications_modifier(infrastructure_level: int, role: str) -> float:
    cfg = _get_war_config().get("fortifications", {})
    step = cfg.get("fortification_defense_bonus_per_level", 0.10)
    if role == "defender":
        return 1.0 + (max(0, infrastructure_level - 1) * step)
    return 1.0


def calculate_home_field_modifier(is_home: bool, role: str) -> float:
    cfg = _get_war_config().get("home_field", {})
    bonus = cfg.get("home_field_defender_bonus", 0.15)
    return (1.0 + bonus) if (role == "defender" and is_home) else 1.0


def calculate_war_support_modifier(war_support: float) -> float:
    cfg = _get_war_config().get("war_support", {})
    scale = cfg.get("war_support_scale", 0.30)
    # baseline war_support = 0.5
    bonus = (war_support - 0.5) * scale
    return max(0.1, 1.0 + bonus)


def evaluate_combat_modifiers(
    action_type: str,
    terrain: str,
    weather: str,
    season: str,
    role: str,
    supply_level: float = 1.0,
    morale: float = 100.0,
    fatigue: float = 0.0,
    experience: float = 10.0,
    own_techs: int = 0,
    enemy_techs: int = 0,
    own_air_power: float = 0.0,
    enemy_air_power: float = 0.0,
    own_naval_power: float = 0.0,
    enemy_naval_power: float = 0.0,
    has_radar: bool = False,
    infrastructure_level: int = 1,
    is_home: bool = False,
    war_support: float = 0.70,
) -> Dict[str, Any]:
    """Computes all modular combat modifiers and returns details dictionary and combined product multiplier."""
    mods = {
        "terrain": calculate_terrain_modifier(action_type, terrain, role),
        "weather": calculate_weather_modifier(action_type, weather),
        "season": calculate_season_modifier(action_type, season, terrain),
        "supply": calculate_supply_modifier(supply_level),
        "morale": calculate_morale_modifier(morale),
        "fatigue": calculate_fatigue_modifier(fatigue),
        "experience": calculate_experience_modifier(experience),
        "tech_gap": calculate_tech_gap_modifier(own_techs, enemy_techs, role),
        "air_superiority": calculate_air_superiority_modifier(own_air_power, enemy_air_power, role),
        "naval_control": calculate_naval_control_modifier(own_naval_power, enemy_naval_power, role),
        "radar": calculate_radar_modifier(has_radar, role),
        "fortifications": calculate_fortifications_modifier(infrastructure_level, role),
        "home_field": calculate_home_field_modifier(is_home, role),
        "war_support": calculate_war_support_modifier(war_support),
    }

    total_mult = 1.0
    for v in mods.values():
        total_mult *= v

    return {
        "breakdown": mods,
        "total_multiplier": max(0.01, round(total_mult, 4)),
    }
