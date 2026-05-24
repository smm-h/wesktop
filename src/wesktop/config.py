"""Config loading utility for wesktop apps.

Provides a standalone TOML config loader with optional Pydantic validation.
Not tied to strictcli's config system -- apps call ``load_config()`` at
startup and pass the result into lifespan state.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def load_config(path: str | Path, schema: type[T] | None = None) -> T | dict[str, Any]:
    """Load a TOML config file.

    Args:
        path: Path to the TOML file.
        schema: Optional Pydantic model class. When provided, the parsed
            TOML dict is validated against the model and a model instance
            is returned. When ``None``, the raw dict is returned.

    Raises:
        FileNotFoundError: If the config file does not exist.
        tomllib.TOMLDecodeError: If the file is not valid TOML.
        pydantic.ValidationError: If *schema* is provided and validation fails.
    """
    path = Path(path)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    if schema is not None:
        return schema.model_validate(data)  # type: ignore[return-value]
    return data
