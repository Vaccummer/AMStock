"""Domain-level exceptions used across application boundaries."""

from __future__ import annotations


class AMStockError(Exception):
    """Base exception for expected application errors."""


class ConfigurationError(AMStockError):
    """Raised when runtime configuration is missing or invalid."""


class ValidationError(AMStockError):
    """Raised when input cannot be accepted by application rules."""


class NotFoundError(AMStockError):
    """Raised when a requested entity cannot be found."""
