from pathlib import Path

import pytest
from fastapi import FastAPI

from finans.api.app import create_app
from finans.settings import Settings
from tests.fakes.access import FakeAccessKeys
from tests.fakes.clock import FixedClock
from tests.support.access import API_SETTINGS, public_jwk
from tests.support.api_client import ApiClient


@pytest.fixture
def keys() -> FakeAccessKeys:
    return FakeAccessKeys([public_jwk()])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "finans.db")


@pytest.fixture
def app(settings: Settings, clock: FixedClock, keys: FakeAccessKeys) -> FastAPI:
    return create_app(settings, API_SETTINGS, keys=keys, clock=clock)


@pytest.fixture
def client(app: FastAPI, clock: FixedClock) -> ApiClient:
    return ApiClient(app, clock)
