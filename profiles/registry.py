"""Profile registry — laadt profielen uit `profiles/*.toml` (versiebeheer).

ChatGPT-correctie 10 mei 2026: profielen leven in versiebeheer, niet in secrets.
Dit module is de enige plek waar Profile-objecten kunnen ontstaan.
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .schema import Profile

_PROFILES_DIR = Path(__file__).parent

# In-memory cache zodat profielen een keer geladen + gevalideerd worden.
PROFILE_REGISTRY: dict[str, Profile] = {}

# TOML-bestanden in profiles/ die geen profielen zijn (config-bestanden).
_NON_PROFILE_TOML = {"tenant_profile_map"}


def _load_profile_from_toml(path: Path) -> Profile:
    """Laad een profiel uit een TOML-bestand. Faalt hard bij parsefout of validatiefout."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return Profile(**raw)


def list_available_profiles() -> list[str]:
    """Lijst alle profile_id's die als TOML-bestand in profiles/ staan."""
    toml_files = [p for p in _PROFILES_DIR.glob("*.toml") if p.is_file()]
    return sorted(p.stem for p in toml_files if p.stem not in _NON_PROFILE_TOML)


def load_profile(profile_id: str) -> Profile:
    """Laad profiel uit TOML, valideer, cache.

    Faalt hard als profiel niet bestaat of inconsistent is.
    """
    if profile_id in PROFILE_REGISTRY:
        return PROFILE_REGISTRY[profile_id]

    toml_path = _PROFILES_DIR / f"{profile_id}.toml"
    if not toml_path.exists():
        available = ", ".join(list_available_profiles()) or "(geen)"
        raise FileNotFoundError(
            f"Profiel '{profile_id}' niet gevonden in {_PROFILES_DIR}. "
            f"Beschikbaar: {available}"
        )

    profile = _load_profile_from_toml(toml_path)
    if profile.profile_id != profile_id:
        raise ValueError(
            f"Bestand {toml_path.name} declareert profile_id='{profile.profile_id}' "
            f"terwijl bestandsnaam '{profile_id}' verwacht. Hernoem een van beide."
        )
    PROFILE_REGISTRY[profile_id] = profile
    return profile


def reload_all() -> dict[str, Profile]:
    """Volledig opnieuw inladen, voor tests en hot-reload."""
    PROFILE_REGISTRY.clear()
    for pid in list_available_profiles():
        load_profile(pid)
    return PROFILE_REGISTRY.copy()
