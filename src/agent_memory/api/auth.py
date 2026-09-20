from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent_memory.api.errors import AuthenticationRequired
from agent_memory.config import Settings
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.observability import annotate, bind_tenant

_bearer = HTTPBearer(auto_error=False)


class JwtPrincipalResolver:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        request: Request,
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
            principal = RequestPrincipal(
                tenant_id=UUID(claims["tenant_id"]),
                user_id=UUID(claims["sub"]),
                roles=frozenset(claims.get("roles", [])),
                permissions=frozenset(claims.get("permissions", [])),
                allowed_workspace_ids=frozenset(claims.get("allowed_workspace_ids", [])),
            )
            self._bind(request, principal)
            return principal
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
            raise AuthenticationRequired from error

    @staticmethod
    def _bind(request: Request, principal: RequestPrincipal) -> None:
        """Publish the tenant to telemetry.

        ``request.state`` is shared with the middleware, while the contextvar
        and the span attribute only reach code running below this dependency --
        Starlette runs the endpoint in a child task, so context set here does
        not propagate back up.
        """
        request.state.tenant_id = str(principal.tenant_id)
        bind_tenant(principal.tenant_id)
        annotate(tenant_id=principal.tenant_id, actor_id=principal.user_id)
