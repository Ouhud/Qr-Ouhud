from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import get_db
from main import app
from models.plan import Plan
from models.qr_share import QRShare
from models.qr_scan import QRScan
from models.qrcode import QRCode
from models.user import User
from models.workspace import Workspace
from models.workspace_member import WorkspaceMember
from models.workspace_qr import WorkspaceQR
from routes.auth import get_current_user


@pytest.fixture
def tenant_test_env():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Minimales Schema fuer Access-Control-Isolationstests
    Plan.__table__.create(bind=engine, checkfirst=True)
    User.__table__.create(bind=engine, checkfirst=True)
    QRCode.__table__.create(bind=engine, checkfirst=True)
    QRScan.__table__.create(bind=engine, checkfirst=True)
    Workspace.__table__.create(bind=engine, checkfirst=True)
    WorkspaceMember.__table__.create(bind=engine, checkfirst=True)
    WorkspaceQR.__table__.create(bind=engine, checkfirst=True)
    QRShare.__table__.create(bind=engine, checkfirst=True)

    current_user_ref = {"user": SimpleNamespace(id=0)}

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user():
        return current_user_ref["user"]

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as client:
        yield client, TestingSessionLocal, current_user_ref

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    engine.dispose()


def _seed_owner_attacker_qr(session_local):
    with session_local() as db:
        owner = User(
            username="tenant_owner",
            email="tenant_owner@example.com",
            password_hash="hash-owner",
        )
        attacker = User(
            username="tenant_attacker",
            email="tenant_attacker@example.com",
            password_hash="hash-attacker",
        )
        db.add_all([owner, attacker])
        db.flush()

        qr = QRCode(
            user_id=owner.id,
            slug="tenant-isolation-slug",
            type="url",
            title="Owner QR",
            dynamic_url="/d/tenant-isolation-slug",
            image_path="static/generated_qr/tenant-test.png",
        )
        qr.set_data({"url": "https://owner.example.com"})
        db.add(qr)
        db.commit()
        db.refresh(qr)
        return owner.id, attacker.id, qr.id, qr.slug


def test_foreign_user_cannot_open_qr_edit_page(tenant_test_env):
    client, session_local, current_user_ref = tenant_test_env
    owner_id, attacker_id, _qr_id, slug = _seed_owner_attacker_qr(session_local)
    assert owner_id != attacker_id

    current_user_ref["user"] = SimpleNamespace(id=attacker_id)
    response = client.get(f"/qr/edit/{slug}")

    assert response.status_code == 403


def test_foreign_user_cannot_update_qr(tenant_test_env):
    client, session_local, current_user_ref = tenant_test_env
    _owner_id, attacker_id, qr_id, slug = _seed_owner_attacker_qr(session_local)

    current_user_ref["user"] = SimpleNamespace(id=attacker_id)
    response = client.post(
        f"/qr/url/update/{qr_id}",
        data={"url": "https://evil.example.com", "title": "Hacked"},
    )
    assert response.status_code == 403

    with session_local() as db:
        qr = db.query(QRCode).filter(QRCode.slug == slug).first()
        assert qr is not None
        assert (qr.get_data() or {}).get("url") == "https://owner.example.com"


def test_owner_can_open_and_update_own_qr(tenant_test_env):
    client, session_local, current_user_ref = tenant_test_env
    owner_id, _attacker_id, qr_id, slug = _seed_owner_attacker_qr(session_local)

    current_user_ref["user"] = SimpleNamespace(id=owner_id)

    edit_response = client.get(f"/qr/edit/{slug}")
    assert edit_response.status_code == 200

    update_response = client.post(
        f"/qr/url/update/{qr_id}",
        data={"url": "https://owner-new.example.com", "title": "Updated Owner QR"},
        follow_redirects=False,
    )
    assert update_response.status_code == 200

    with session_local() as db:
        qr = db.query(QRCode).filter(QRCode.slug == slug).first()
        assert qr is not None
        assert (qr.get_data() or {}).get("url") == "https://owner-new.example.com"
