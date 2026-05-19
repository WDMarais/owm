"""
Integration tests for database operations — real Postgres, no mocks.
Covers: create_db, reset_db, check_pg_reachability, db_dump, db_restore.

Skip entirely if Postgres is not reachable:
    uv run pytest -m 'not integration'
"""
import uuid
import subprocess
import pytest

from owm.database import create_db, reset_db, check_pg_reachability, _pg_isready
from owm.operations import db_dump, db_restore
from owm.errors import OwmError, DB_UNAVAILABLE

_PG_HOST = "/var/run/postgresql"
_PG_PORT = 5432
_PG_ARGS = ["-h", _PG_HOST, "-p", str(_PG_PORT)]


def _pg_reachable() -> bool:
    r = subprocess.run(["pg_isready", *_PG_ARGS], capture_output=True)
    return r.returncode == 0


def _db_exists(name: str) -> bool:
    r = subprocess.run(
        ["psql", *_PG_ARGS, "-lqt"],
        capture_output=True, text=True,
    )
    return any(line.strip().startswith(name + " ") or line.strip().startswith(name + "|")
               for line in r.stdout.splitlines())


def _drop_if_exists(name: str) -> None:
    subprocess.run(["dropdb", *_PG_ARGS, "--if-exists", name], capture_output=True)


@pytest.fixture(scope="module", autouse=True)
def require_postgres():
    if not _pg_reachable():
        pytest.skip("Postgres not reachable — skipping integration tests")


@pytest.fixture
def tmp_db_name():
    name = f"owm_test_{uuid.uuid4().hex[:8]}"
    yield name
    _drop_if_exists(name)


@pytest.fixture
def tmp_template_db(tmp_db_name):
    """Create a blank DB to serve as a template, yield its name, drop on teardown."""
    subprocess.run(["createdb", *_PG_ARGS, tmp_db_name], check=True, capture_output=True)
    # Mark it as a template so createdb --template= works
    subprocess.run(
        ["psql", *_PG_ARGS, "-c", f"UPDATE pg_database SET datistemplate=true WHERE datname='{tmp_db_name}'"],
        capture_output=True,
    )
    yield tmp_db_name
    subprocess.run(
        ["psql", *_PG_ARGS, "-c", f"UPDATE pg_database SET datistemplate=false WHERE datname='{tmp_db_name}'"],
        capture_output=True,
    )
    _drop_if_exists(tmp_db_name)


# ---------------------------------------------------------------------------
# pg_isready
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_smoke_pg_isready_raises_on_bad_port():
    with pytest.raises(OwmError) as exc_info:
        _pg_isready(_PG_HOST, 19999)
    assert exc_info.value.code == DB_UNAVAILABLE


@pytest.mark.integration
def test_smoke_check_pg_reachability_returns_result():
    result = check_pg_reachability(_PG_HOST, _PG_PORT)
    assert result.method == "pg_isready"
    assert result.host == _PG_HOST
    assert result.port == _PG_PORT


# ---------------------------------------------------------------------------
# create_db
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_smoke_create_db_blank_creates_database(tmp_db_name):
    result = create_db(name=tmp_db_name, odoo_version="19", template=None, pg_port=_PG_PORT)
    assert result.source == "blank"
    assert _db_exists(tmp_db_name)


@pytest.mark.integration
def test_smoke_create_db_from_template(tmp_template_db):
    target = f"owm_test_{uuid.uuid4().hex[:8]}"
    try:
        result = create_db(name=target, odoo_version="19", template=tmp_template_db, pg_port=_PG_PORT)
        assert result.source == "template"
        assert _db_exists(target)
    finally:
        _drop_if_exists(target)


# ---------------------------------------------------------------------------
# reset_db
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_smoke_reset_db_drops_and_recreates(tmp_template_db):
    db = f"owm_test_{uuid.uuid4().hex[:8]}"
    subprocess.run(["createdb", *_PG_ARGS, db], check=True, capture_output=True)
    try:
        result = reset_db(name=db, template=tmp_template_db, pg_port=_PG_PORT, seed_script=None)
        assert result.restored_from == tmp_template_db
        assert _db_exists(db)
    finally:
        _drop_if_exists(db)


# ---------------------------------------------------------------------------
# db_dump / db_restore
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_smoke_db_dump_creates_file(tmp_db_name, tmp_path):
    subprocess.run(["createdb", *_PG_ARGS, tmp_db_name], check=True, capture_output=True)
    out = str(tmp_path / "snapshot.dump")
    result = db_dump(
        instance="smoke-test", out=out, workspace_root=str(tmp_path),
        db_name=tmp_db_name, pg_port=_PG_PORT,
    )
    import os
    assert result.path == out
    assert os.path.isfile(out)
    assert os.path.getsize(out) > 0


@pytest.mark.integration
def test_smoke_db_restore_into_blank_db(tmp_db_name, tmp_path):
    subprocess.run(["createdb", *_PG_ARGS, tmp_db_name], check=True, capture_output=True)
    dump_path = str(tmp_path / "snapshot.dump")
    db_dump(
        instance="smoke-test", out=dump_path, workspace_root=str(tmp_path),
        db_name=tmp_db_name, pg_port=_PG_PORT,
    )
    # drop and recreate blank target
    _drop_if_exists(tmp_db_name)
    subprocess.run(["createdb", *_PG_ARGS, tmp_db_name], check=True, capture_output=True)
    result = db_restore(
        instance="smoke-test", path=dump_path, workspace_root=str(tmp_path),
        db_name=tmp_db_name, pg_port=_PG_PORT,
    )
    assert result.resolved_path == dump_path
