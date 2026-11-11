from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from growshed.config import Settings
from growshed.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def settings(tmp_path):
    return Settings(
        config_path=REPO_ROOT / "config" / "config.yaml",
        db_path=tmp_path / "test.db",
        static_dir=tmp_path / "no-frontend",
        mqtt_enabled=False,
        background_enabled=False,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c
