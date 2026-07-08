"""Sync and async test clients re-exported from fastware for exercising wesktop ASGI routes without starting a real network server or GUI window."""

from fastware.testing import *  # noqa: F401,F403

# TestClient is intentionally absent from fastware.testing.__all__ (pytest
# would collect it as a test class), so it must be imported explicitly.
from fastware.testing import TestClient  # noqa: F401
