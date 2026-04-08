"""Optional API-key authentication for Studio / admin endpoints.

Activated by setting the env var ``STUDIO_API_KEY``. Clients must then send
the same value in the ``X-Studio-Key`` HTTP header (or ``?key=…`` query
param). If the env var is empty/unset, the dependency is a no-op and all
endpoints stay open — convenient for local development.

Use as a FastAPI dependency:

    from app.services.auth import require_studio_key

    @router.put("/file", dependencies=[Depends(require_studio_key)])
    async def update(...): ...
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException, Query, status

_HEADER = "X-Studio-Key"


def _expected_key() -> str:
    return (os.getenv("STUDIO_API_KEY") or "").strip()


async def require_studio_key(
    x_studio_key: str | None = Header(default=None, alias=_HEADER),
    key: str | None = Query(default=None),
) -> None:
    """FastAPI dependency. Raises 401 when an API key is configured but the
    request did not provide a matching one. No-op when no key is configured.
    """
    expected = _expected_key()
    if not expected:
        return  # auth disabled
    provided = (x_studio_key or key or "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Studio API key required",
            headers={"WWW-Authenticate": _HEADER},
        )
