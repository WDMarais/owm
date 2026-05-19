"""
Tests for database creation, cloning, reset, and template management.
Covers: Database lifecycle, Database auth sections.
"""
import subprocess
import pytest
from unittest.mock import patch

from owm.database import create_db, reset_db, sync_db_from_template
from owm.database import check_template_staleness, check_pg_reachability
from owm.database import DatabaseConfig, TemplateStatus
from owm.instance import generate_instance_conf
from owm.workspace import init_workspace


# ---------------------------------------------------------------------------
# DB creation
# ---------------------------------------------------------------------------

@pytest.mark.database_lifecycle
def test_create_db_clones_from_template_when_available():
    with patch("owm.database._createdb"):
        result = create_db(
            name="odoo19_feat789",
            odoo_version="19",
            template="odoo19_base",
            pg_port=5432,
        )
    assert result.source == "template"
    assert result.template == "odoo19_base"
    assert result.full_install_required is False


@pytest.mark.database_lifecycle
def test_create_db_blank_slate_when_no_template():
    """No base template for this Odoo version → blank slate + slow-install warning."""
    with patch("owm.database._createdb"):
        result = create_db(
            name="odoo19_feat789",
            odoo_version="19",
            template=None,
            pg_port=5432,
        )
    assert result.source == "blank"
    assert result.full_install_required is True
    assert result.warning is not None
    assert "slow" in result.warning.lower() or "install" in result.warning.lower()


@pytest.mark.database_lifecycle
def test_create_db_uses_unix_socket_connection():
    with patch("owm.database._createdb"):
        result = create_db(
            name="odoo19_feat789",
            odoo_version="19",
            template=None,
            pg_port=5432,
        )
    assert result.connection.host.startswith("/var/run/postgresql") or result.connection.host is None
    assert result.connection.password is None


@pytest.mark.database_lifecycle
def test_create_db_owned_by_operator_user():
    """No per-instance Postgres roles; DB owned by operator user directly."""
    with patch("owm.database._createdb"):
        result = create_db(
            name="odoo19_feat789",
            odoo_version="19",
            template=None,
            pg_port=5432,
        )
    assert result.owner == result.operator_user
    assert result.per_instance_role is False


# ---------------------------------------------------------------------------
# db-reset
# ---------------------------------------------------------------------------

@pytest.mark.database_lifecycle
def test_db_reset_restores_from_base_template():
    with patch("owm.database._dropdb"), patch("owm.database._createdb"):
        result = reset_db(
            name="odoo19_feat789",
            template="odoo19_base",
            pg_port=5432,
            seed_script=None,
        )
    assert result.restored_from == "odoo19_base"


@pytest.mark.database_lifecycle
def test_db_reset_with_seed_script_reruns_it():
    with patch("owm.database._dropdb"), patch("owm.database._createdb"):
        result = reset_db(
            name="odoo19_feat789",
            template="odoo19_base",
            pg_port=5432,
            seed_script="scripts/seed.py",
        )
    assert result.restored_from == "odoo19_base"
    assert result.seed_script_run is True
    assert result.seed_script == "scripts/seed.py"


@pytest.mark.database_lifecycle
def test_db_reset_no_seed_script_warns_instance_state_not_restored():
    with patch("owm.database._dropdb"), patch("owm.database._createdb"):
        result = reset_db(
            name="odoo19_feat789",
            template="odoo19_base",
            pg_port=5432,
            seed_script=None,
        )
    assert result.warning is not None
    assert "instance-specific state" in result.warning.lower() or "not restored" in result.warning.lower()


# ---------------------------------------------------------------------------
# Template staleness
# ---------------------------------------------------------------------------

@pytest.mark.database_lifecycle
def test_template_refresh_does_not_sync_existing_instances():
    """Base template refresh → no automatic sync to running instances."""
    result = sync_db_from_template(
        template="odoo19_base",
        instances=["feat-789", "review-101"],
        auto_sync=False,
    )
    assert result.synced_instances == []
    assert result.affected_instances == ["feat-789", "review-101"]


@pytest.mark.database_lifecycle
def test_template_staleness_warning_on_status_check():
    """Instance whose template is older than threshold → warning on next status check."""
    result = check_template_staleness(
        template_age_days=35,
        threshold_days=30,
        instance="feat-789",
    )
    assert result.stale is True
    assert result.warning is not None


@pytest.mark.database_lifecycle
def test_template_staleness_no_warning_within_threshold():
    result = check_template_staleness(
        template_age_days=20,
        threshold_days=30,
        instance="feat-789",
    )
    assert result.stale is False
    assert result.warning is None


@pytest.mark.database_lifecycle
def test_template_sync_opt_in_creates_backup_first():
    with patch("owm.database.subprocess.run"):
        result = sync_db_from_template(
            template="odoo19_base",
            instance="feat-789",
            opt_in=True,
        )
    assert result.backup_created is True
    assert result.backup_path is not None


@pytest.mark.database_lifecycle
def test_template_sync_failure_restores_backup():
    with patch("owm.database.subprocess.run") as mock_run:
        mock_run.side_effect = [
            None,  # pg_dump backup
            subprocess.CalledProcessError(1, "dropdb"),  # sync step fails
            None,  # createdb for restore
            None,  # pg_restore
        ]
        result = sync_db_from_template(
            template="odoo19_base",
            instance="feat-789",
            opt_in=True,
        )
    assert result.backup_restored is True
    assert result.error is not None


@pytest.mark.database_lifecycle
def test_template_sync_opt_out_no_action():
    result = sync_db_from_template(
        template="odoo19_base",
        instance="feat-789",
        opt_in=False,
    )
    assert result.synced is False
    assert result.backup_created is False


# ---------------------------------------------------------------------------
# Database auth — local model
# ---------------------------------------------------------------------------

@pytest.mark.database_lifecycle
@pytest.mark.database_auth
def test_pg_reachability_check_uses_pg_isready():
    """Health check: pg_isready -h /var/run/postgresql -p <port>."""
    result = check_pg_reachability(pg_host="/var/run/postgresql", pg_port=5432)
    assert result.method == "pg_isready"
    assert result.host == "/var/run/postgresql"
    assert result.port == 5432


@pytest.mark.database_lifecycle
@pytest.mark.database_auth
def test_odoo_conf_includes_dbfilter():
    """Generated instance.conf sets dbfilter = ^<name>$ for subdomain isolation."""
    conf = generate_instance_conf(instance_name="feat-789", http_port=8142, gevent_port=8143, workers=2)
    dbfilter = conf.get("dbfilter") if isinstance(conf, dict) else None
    assert dbfilter == "^feat-789$" or "dbfilter = ^feat-789$" in str(conf)


_DB_WS_TOML = '[repos]\nodoo = "git@github.com:odoo/odoo.git"\n[clusters]\n"19" = {pg_version = "16", port = 5432}\n'


@pytest.mark.database_lifecycle
@pytest.mark.database_auth
def test_init_creates_operator_superuser_role_if_absent(tmp_path):
    """owm init: createuser --superuser $(whoami) if role absent; idempotent."""
    (tmp_path / "workspace.toml").write_text(_DB_WS_TOML)
    with patch("owm.workspace._superuser_exists", return_value=False), \
         patch("owm.workspace._git_clone_bare"), \
         patch("owm.workspace.subprocess.run"):
        result = init_workspace(str(tmp_path), operator_user="devuser")
    assert result.postgres.superuser_created is True
    assert result.postgres.superuser_role == "devuser"


@pytest.mark.database_lifecycle
@pytest.mark.database_auth
def test_init_superuser_already_exists_is_idempotent(tmp_path):
    (tmp_path / "workspace.toml").write_text(_DB_WS_TOML)
    with patch("owm.workspace._superuser_exists", return_value=True), \
         patch("owm.workspace._git_clone_bare"):
        result = init_workspace(str(tmp_path), operator_user="devuser")
    assert result.postgres.superuser_created is False
    assert result.postgres.skipped is True


# === SPEC GAPS ===
# test_db_unreachable_on_create: spec defines DB_UNAVAILABLE code but does not specify
#   exactly which create-step triggers it or what partial cleanup happens.
# test_template_version_tracking: spec mentions "5 template versions" as staleness signal
#   alongside days-based threshold; version-count tracking not elaborated.
# test_create_db_cluster_selection: workspace.toml maps Odoo version → cluster/pg_port;
#   the lookup logic (how version string maps to cluster key) is not fully specced.
