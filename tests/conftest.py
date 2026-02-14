from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import word_assistance.app as app_module
from word_assistance.storage.db import Database


@pytest.fixture()
def temp_db(tmp_path):
    db = Database(tmp_path / "word_assistance_test.db")
    db.initialize()
    return db


@pytest.fixture()
def client(temp_db, monkeypatch):
    monkeypatch.setattr(app_module, "db", temp_db)
    with TestClient(app_module.app) as c:
        yield c
