import os
from datetime import date
import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from backend.db.session import Base
from backend.demo import dataset, run_request
from backend.tools.procurement import ProcurementTools
from backend.models.entities import (
    LEGACY_ORGANIZATION_ID, LEGACY_WORKSPACE_ID, Organization, Workspace,
)


@pytest.fixture
def db():
    # TEST_DATABASE_URL must point to a disposable, dedicated test database.
    url = os.getenv("TEST_DATABASE_URL")
    if url and not (make_url(url).database or "").endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL must target a disposable database whose name ends in _test")
    engine = create_engine(url) if url else create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if not url:
        @event.listens_for(engine, "connect")
        def fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(Organization(id=LEGACY_ORGANIZATION_ID, name="Synthetic Office Co."))
        session.add(Workspace(
            id=LEGACY_WORKSPACE_ID, org_id=LEGACY_ORGANIZATION_ID, name="Demo workspace",
            business_entity="Synthetic Office Co.", warehouse="SYNTHETIC-WH-1", currency="SGD",
            finance_threshold=5000,
        ))
        session.commit()
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def t(db):
    return ProcurementTools(db, actor="Test Reviewer", human=True)


@pytest.fixture
def data():
    return dataset(date(2026, 9, 27), with_exceptions=False)


@pytest.fixture
def start(t, data):
    def execute(modified=None):
        batch = t.import_dataset(modified if modified is not None else data)
        assert batch["status"].startswith("VALIDATED"), batch
        run = t.create_procurement_run(run_request(batch["id"], date(2026, 9, 27)))
        t.run_full_check(run["id"])
        return run["id"]
    return execute
