"""Profielen — capability contracts in versiebeheer.

ChatGPT-correctie 10 mei 2026: profielen MOGEN NIET in secrets staan.
Secrets bevatten alleen authenticatie (tokens, wachtwoorden).
Profielen bepalen productlogica en horen in versiebeheer.
"""
from .schema import (
    Profile,
    Capabilities,
    RefusalPolicy,
    PromptPolicy,
    Tier,
    QuestionScope,
)
from .registry import (
    load_profile,
    list_available_profiles,
    PROFILE_REGISTRY,
)

__all__ = [
    "Profile",
    "Capabilities",
    "RefusalPolicy",
    "PromptPolicy",
    "Tier",
    "QuestionScope",
    "load_profile",
    "list_available_profiles",
    "PROFILE_REGISTRY",
]
