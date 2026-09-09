"""测试环境：mock 慢道、零演示延时、临时存储目录（须在 app 导入前设置）。"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ["VIZGUIDE_LLM_MODE"] = "mock"
os.environ["VIZGUIDE_MOCK_BEAT_DELAY_MS"] = "0"
os.environ["VIZGUIDE_STORAGE_DIR"] = tempfile.mkdtemp(prefix="vizguide-test-")


@pytest.fixture(scope="session")
def example_spec() -> dict:
    with open(REPO_ROOT / "data" / "example.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def registry():
    from app.config import settings
    from app.core.persona import PersonaRegistry

    return PersonaRegistry(data_dir=settings.data_dir, custom_dir=settings.storage_dir / "personas")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
