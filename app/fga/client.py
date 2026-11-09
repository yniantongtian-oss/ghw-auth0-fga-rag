"""Pick the in-memory evaluator or the HTTP client from settings."""

from __future__ import annotations

import time

from app.config import Settings
from app.fga.dsl import Model
from app.fga.http import FgaError, HttpFga
from app.fga.memory import MemoryFga, Tuple, validate_tuples

__all__ = ["FgaError", "HttpFga", "MemoryFga", "build_fga"]


def build_fga(
    settings: Settings,
    model: Model,
    tuples: list[Tuple],
    inventory: dict[str, list[str]],
) -> MemoryFga | HttpFga:
    validate_tuples(model, tuples)
    if not settings.fga_api_url:
        return MemoryFga(model, tuples, inventory)
    client = HttpFga(settings)
    if settings.fga_auto_bootstrap:
        last_error: FgaError | None = None
        for attempt in range(8):
            try:
                client.bootstrap(model, tuples, settings.fga_store_name)
                return client
            except FgaError as exc:
                last_error = exc
                time.sleep(0.4 * (attempt + 1))
        raise FgaError(f"could not bootstrap OpenFGA: {last_error}")
    if not client.store_id:
        raise FgaError("Set FGA_STORE_ID, or enable FGA_AUTO_BOOTSTRAP for local OpenFGA")
    return client
