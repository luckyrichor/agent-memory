"""Bound the complete body before parsing, authentication dependencies or database writes."""
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimit:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        async def reject(status: int, code: str) -> None:
            response = JSONResponse(status_code=status, content={'error': {
                'code': code, 'message': 'Request body rejected.', 'retryable': False,
                'request_id': scope.get('state', {}).get('request_id', 'unavailable')}})
            await response(scope, receive, send)

        headers = dict(scope.get('headers', []))
        length = headers.get(b'content-length')
        if length is not None:
            if not length.isdigit():
                await reject(400, 'INVALID_CONTENT_LENGTH')
                return
            # Avoid parsing attacker-controlled integers with thousands of digits.
            if len(length) > 12 or int(length) > self.max_bytes:
                await reject(413, 'REQUEST_BODY_TOO_LARGE')
                return
        data = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            if len(data) + len(chunk) > self.max_bytes:
                await reject(413, 'REQUEST_BODY_TOO_LARGE')
                return
            data.extend(chunk)
            if not message.get('more_body', False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(data), 'more_body': False}
            # Keep the real disconnect semantics after the replayed body.
            return await receive()

        await self.app(scope, replay, send)
