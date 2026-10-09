from enum import StrEnum


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    REVIEW_REQUIRED = "review_required"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"


class WorkflowStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ENQUEUE_FAILED = "enqueue_failed"


class EvidenceStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTESTED = "contested"
    UNSUPPORTED = "unsupported"
    SOURCE_EXPIRED = "source_expired"


class OutcomeStatus(StrEnum):
    PENDING = "pending"
    MONITORING = "monitoring"
    VERIFIED = "verified"
    PARTIAL = "partial"
    FALSIFIED = "falsified"
    INCONCLUSIVE = "inconclusive"
    EXPIRED = "expired"


class ConfidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    INSUFFICIENT = "Insufficient"


class ChainStatus(StrEnum):
    DRAFT = "draft"
    FULLY_SUPPORTED = "fully_supported"
    MOSTLY_SUPPORTED = "mostly_supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    BROKEN = "broken"
    INCONCLUSIVE = "inconclusive"
    REVIEW_REQUIRED = "review_required"
    PUBLISHED = "published"


class PublicationDecision(StrEnum):
    PUBLISH = "publish"
    REVIEW = "review"
    REJECT = "reject"


class ReviewDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SourceTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class EntailmentStatus(StrEnum):
    DIRECTLY_SUPPORTS = "directly_supports"
    PARTIALLY_SUPPORTS = "partially_supports"
    DOES_NOT_SUPPORT = "does_not_support"
    CONTRADICTS = "contradicts"
