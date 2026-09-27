# by @NotYoursNaruto
# curl_compat — ChromeSession shim for the Adyen engine.
#
# The engine calls `session.get(url)` / `session.post(url)` and uses the result
# with `async with ... as resp:`, where `resp` is the fully-materialized response
# (`.text`, `.json()`, `.status_code`, `.url`). curl_cffi's AsyncSession returns
# *coroutines* instead, so this shim wraps them into an awaitable that is also an
# async context manager. Backed by curl_cffi for real Chrome TLS fingerprints.
"""ChromeSession: async HTTP session with browser TLS fingerprint impersonation."""

try:
    from curl_cffi.requests import AsyncSession as _CurlAsyncSession
    _HAS_CFFI = True
except ImportError:  # pragma: no cover
    _HAS_CFFI = False


class _Response:
    """An awaitable response that doubles as an async context manager."""

    def __init__(self, coro):
        self._coro = coro

    def __await__(self):
        return self._coro.__await__()

    async def __aenter__(self):
        self._resp = await self._coro
        return self._resp

    async def __aexit__(self, exc_type, exc, tb):
        return False


if _HAS_CFFI:

    class ChromeSession:
        """curl_cffi-backed async session exposing context-manager-style requests."""

        def __init__(self, impersonate=None, proxies=None, timeout=12, **kw):
            self._sess = _CurlAsyncSession(
                impersonate=impersonate, proxies=proxies, timeout=timeout, **kw
            )

        async def __aenter__(self):
            await self._sess.__aenter__()
            return self

        async def __aexit__(self, exc_type, exc, tb):
            await self._sess.__aexit__(exc_type, exc, tb)

        def get(self, url, **kw):
            return _Response(self._sess.get(url, **kw))

        def post(self, url, **kw):
            return _Response(self._sess.post(url, **kw))

else:  # pragma: no cover
    import httpx

    class _HttpxResponse:
        def __init__(self, coro):
            self._coro = coro

        def __await__(self):
            return self._coro.__await__()

        async def __aenter__(self):
            self._resp = await self._coro
            return self._resp

        async def __aexit__(self, exc_type, exc, tb):
            await self._resp.aclose()
            return False

    class ChromeSession:
        """httpx fallback (no TLS impersonation) — install curl_cffi for real fingerprinting."""

        def __init__(self, impersonate=None, proxies=None, timeout=12, **kw):
            self._client = httpx.AsyncClient(proxies=proxies, timeout=timeout, **kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            await self._client.aclose()

        def get(self, url, **kw):
            return _HttpxResponse(self._client.get(url, **kw))

        def post(self, url, **kw):
            return _HttpxResponse(self._client.post(url, **kw))


__all__ = ["ChromeSession"]
