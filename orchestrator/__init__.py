"""Orchestrator — leest profiel, valideert capabilities, laadt enabled adapters.

ChatGPT-correctie 10 mei 2026: fail-fast bij inconsistent profiel.
App start NIET als adapter ontbreekt of capability geen ondersteunende adapter heeft.
"""
from .source_loader import (
    SourceLoader,
    SourceLoaderError,
    InconsistentProfileError,
    AdapterImportError,
    AdapterCredentialsError,
)
from .profile_loader import (
    resolve_tenant_to_profile,
    load_active_profile,
    TenantNotMappedError,
)
from .question_router import (
    classify_question_scope,
    QuestionScopeClassifier,
)

__all__ = [
    "SourceLoader",
    "SourceLoaderError",
    "InconsistentProfileError",
    "AdapterImportError",
    "AdapterCredentialsError",
    "resolve_tenant_to_profile",
    "load_active_profile",
    "TenantNotMappedError",
    "classify_question_scope",
    "QuestionScopeClassifier",
]
