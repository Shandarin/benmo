class WorkerError(Exception):
    """Base error for an expected worker failure."""


class ConfigurationError(WorkerError):
    """The selected provider cannot be configured safely."""


class PermanentTaskError(WorkerError):
    """A malformed task that must not be retried."""


class RetryableTaskError(WorkerError):
    """A transient failure for which the queue should retry delivery."""


class IntegrityError(PermanentTaskError):
    """Stored or quoted content failed an integrity constraint."""


class AlreadyExistsWithDifferentContent(IntegrityError):
    """An immutable key was reused for different bytes."""
