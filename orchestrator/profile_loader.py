"""Profile loader — koppelt tenant aan profiel via versie-beheerd map-bestand.

ChatGPT-anti-spoofing: tenant-profiel-mapping staat in versiebeheer
(profiles/tenant_profile_map.toml), niet in secrets. Secrets bevatten alléén
credentials.
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from profiles.registry import load_profile
from profiles.schema import Profile

_TENANT_MAP_PATH = Path(__file__).parent.parent / "profiles" / "tenant_profile_map.toml"


class TenantNotMappedError(RuntimeError):
    """Tenant heeft geen profiel-mapping — fail-fast."""


def _load_tenant_map() -> dict:
    if not _TENANT_MAP_PATH.exists():
        raise FileNotFoundError(f"Tenant-profile mapping ontbreekt: {_TENANT_MAP_PATH}")
    with _TENANT_MAP_PATH.open("rb") as f:
        return tomllib.load(f)


def resolve_tenant_to_profile(tenant_id: str) -> str:
    """Geef profile_id voor deze tenant. Faalt als tenant niet gemapt is."""
    tenant_map = _load_tenant_map()
    if tenant_id not in tenant_map:
        available = ", ".join(sorted(tenant_map.keys())) or "(geen)"
        raise TenantNotMappedError(
            f"Tenant '{tenant_id}' heeft geen profiel-toewijzing. "
            f"Beschikbare tenants: {available}. "
            f"Voeg een entry toe aan {_TENANT_MAP_PATH.name}."
        )
    entry = tenant_map[tenant_id]
    if not isinstance(entry, dict) or "profile_id" not in entry:
        raise TenantNotMappedError(
            f"Tenant '{tenant_id}' is gemapt maar zonder 'profile_id'. "
            f"Repareer {_TENANT_MAP_PATH.name}."
        )
    return entry["profile_id"]


def load_active_profile(tenant_id: str) -> Profile:
    """Resolve tenant → profile_id → Profile. Fail-fast bij inconsistentie.

    Tweede veiligheidscheck: als profiel `allowed_for_tenants` invult, moet
    tenant_id daarin staan. Niet ingevulde lijst = wildcard.
    """
    profile_id = resolve_tenant_to_profile(tenant_id)
    profile = load_profile(profile_id)

    if profile.allowed_for_tenants and tenant_id not in profile.allowed_for_tenants:
        raise TenantNotMappedError(
            f"Tenant '{tenant_id}' is gemapt op profiel '{profile_id}', maar het profiel "
            f"beperkt zich tot {profile.allowed_for_tenants}. Inconsistentie tussen "
            f"profiel-config en tenant-mapping. Repareer."
        )
    return profile
