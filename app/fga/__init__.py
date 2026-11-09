"""Auth0 FGA / OpenFGA model, in-memory evaluation, and HTTP client."""

from app.fga.client import FgaError, build_fga
from app.fga.dsl import ModelError, parse_model

__all__ = ["FgaError", "ModelError", "build_fga", "parse_model"]
