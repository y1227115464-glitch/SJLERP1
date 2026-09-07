from tempfile import SpooledTemporaryFile

from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    """Bound the actual streamed body before multipart parsing, including chunked uploads."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        # A bounded spool avoids keeping large multipart bodies in RAM. It is closed
        # even when the client disconnects or downstream validation rejects input.
        with SpooledTemporaryFile(max_size=1024 * 1024) as body:
            total = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > self.max_bytes:
                    response = JSONResponse(status_code=413, content={"error": {"code": "request_too_large", "message": "请求超过大小限制"}})
                    await response(scope, receive, send)
                    return
                body.write(chunk)
                if not message.get("more_body", False):
                    break
            body.seek(0)
            remaining = total

            async def bounded_receive():
                nonlocal remaining
                if remaining <= 0:
                    return await receive()
                chunk = body.read(min(remaining, 64 * 1024))
                remaining -= len(chunk)
                return {"type": "http.request", "body": chunk, "more_body": remaining > 0}

            async def empty_receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, bounded_receive if total else empty_receive, send)
