from enum import Enum


class QualityStatus(str, Enum):
    PENDING = "pending"
    RENDERING = "rendering"
    FAILED = "failed"
    PASSED = "passed"
    STALE = "stale"
