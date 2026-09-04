"""Minimal aiohttp stand-in so api.py can be exercised without the real library."""
import asyncio, types, sys

class ClientError(Exception): ...
class ServerDisconnectedError(ClientError):
    def __str__(self): return ""          # the empty-message case from the log

class ClientTimeout:
    def __init__(self, total=None): self.total = total

class _Resp:
    def __init__(self, text): self._t = text
    async def text(self, errors=None): return self._t
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

class _Fail:
    def __init__(self, exc): self.exc = exc
    async def __aenter__(self): raise self.exc
    async def __aexit__(self, *a): return False

class ClientSession:
    """Replays a scripted list of outcomes; records every call."""
    def __init__(self, outcomes): self.outcomes = list(outcomes); self.calls = []
    def get(self, url, timeout=None):
        self.calls.append((url, timeout.total if timeout else None))
        out = self.outcomes.pop(0) if self.outcomes else "A+"
        return _Fail(out) if isinstance(out, BaseException) else _Resp(out)

mod = types.ModuleType("aiohttp")
mod.ClientError = ClientError
mod.ServerDisconnectedError = ServerDisconnectedError
mod.ClientTimeout = ClientTimeout
mod.ClientSession = ClientSession
sys.modules["aiohttp"] = mod
