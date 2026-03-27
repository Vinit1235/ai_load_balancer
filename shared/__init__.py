"""Shared utilities and configurations"""

from shared.self_correction import (
    SelfCorrectionEngine,
    RetryConfig,
    ErrorContext,
    ErrorCategory,
    ErrorSeverity,
    CorrectionResult,
    correction_engine,
    with_self_correction
)

__all__ = [
    "SelfCorrectionEngine",
    "RetryConfig", 
    "ErrorContext",
    "ErrorCategory",
    "ErrorSeverity",
    "CorrectionResult",
    "correction_engine",
    "with_self_correction"
]
