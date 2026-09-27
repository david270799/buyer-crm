"""Errors whose message is safe to show to a user.

Anything that is *not* a CRMError is treated as an internal failure: it is
logged with a stack trace and the user only sees a generic message.
"""


class CRMError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.user_message = message


class NotFoundError(CRMError):
    pass


class ValidationError(CRMError):
    pass


class ConflictError(CRMError):
    """The requested change contradicts the current state of the data."""


class PermissionDeniedError(CRMError):
    pass


class ConfigurationError(CRMError):
    pass
