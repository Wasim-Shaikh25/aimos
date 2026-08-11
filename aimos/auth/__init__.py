"""Single-user authentication for the dashboard and protected API endpoints."""

from aimos.auth.security import AuthError, decode_token, get_current_user

__all__ = ["AuthError", "decode_token", "get_current_user"]
