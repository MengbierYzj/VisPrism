"""LLM 客户端重试与连接池恢复。"""
from types import SimpleNamespace

from app.llm import LLMClient


class FakeCompletions:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    async def create(self, **kwargs):
        if self.error:
            raise self.error
        message = SimpleNamespace(content=self.result)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeOpenAIClient:
    def __init__(self, result=None, error=None):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(result=result, error=error)
        )
        self.closed = False

    async def close(self):
        self.closed = True


class SequencedLLMClient(LLMClient):
    def __init__(self, clients):
        super().__init__()
        self.clients = list(clients)
        self.build_count = 0

    def _build_client(self):
        self.build_count += 1
        return self.clients.pop(0)


def test_retry_rebuilds_client_after_timeout(monkeypatch):
    import asyncio

    monkeypatch.setenv("VIZGUIDE_LLM_MODE", "live")
    failed = FakeOpenAIClient(error=TimeoutError("upstream timed out"))
    recovered = FakeOpenAIClient(result='{"ok": true}')
    llm = SequencedLLMClient([failed, recovered])

    result = asyncio.run(llm.chat_json("system", "user", retries=1))

    assert result == {"ok": True}
    assert llm.build_count == 2
    assert failed.closed is True

