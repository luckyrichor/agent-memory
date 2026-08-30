from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent_memory.api.errors import AuthenticationRequired
from agent_memory.config import Settings
from agent_memory.domain.principal import RequestPrincipal

_bearer = HTTPBearer(auto_error=False)


class JwtPrincipalResolver:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(_bearer),
        ],
    ) -> RequestPrincipal:
        if credentials is None:
            raise AuthenticationRequired
        try:
            claims = jwt.decode(
                credentials.credentials,
                self._settings.jwt_public_key,
                algorithms=["RS256"],
                issuer=self._settings.jwt_issuer,
                audience=self._settings.jwt_audience,
            )
            return RequestPrincipal(
                tenant_id=UUID(claims["tenant_id"]),
                user_id=UUID(claims["sub"]),
                roles=frozenset(claims.get("roles", [])),
                permissions=frozenset(claims.get("permissions", [])),
                allowed_workspace_ids=frozenset(claims.get("allowed_workspace_ids", [])),
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
            raise AuthenticationRequired from error
