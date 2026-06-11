"""
Tests for remaining CLI commands: delete, rename, logs, shell, db-dump/restore, validate.
Also covers: CWD inference, Log rotation sections.
"""
import json
import pytest
from unittest.mock import patch

from owm.operations import delete_instance, rename_instance, show_logs
from owm.operations import db_dump, db_restore, validate_instance
from owm.operations import infer_instance_from_cwd
from owm.log_rotation import check_rotation_needed, rotate_log


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

@pytest.mark.cli_commands
def test_delete_running_instance_hard_error():
    with pytest.raises(Exception) as exc_info:
        delete_instance(instance="feat-789", running=True, force=False)
    assert "INSTANCE_RUNNING" in str(exc_info.value) or "stop" in str(exc_info.value).lower()


@pytest.mark.cli_commands
def test_delete_stopped_no_force_shows_checklist():
    result = delete_instance(
        instance="feat-789",
        running=False,
        force=False,
        has_session_notes=True,
        open_compare_pairs=["main"],
    )
    assert result.status == "pending_confirmation"
    assert result.checklist is not None
    assert len(result.checklist) > 0


@pytest.mark.cli_commands
def test_delete_force_skips_checklist_and_removes_all(standard_instance_toml, tmp_workspace):
    with patch("owm.operations._remove_worktrees"), \
         patch("owm.operations._dropdb_archive"), \
         patch("owm.operations._remove_proxy_block"), \
         patch("owm.operations.shutil.rmtree"):
        result = delete_instance(
            instance="feat-789",
            running=False,
            force=True,
            workspace_root=str(tmp_workspace),
        )
    assert result.status == "deleted"
    assert result.worktrees_removed is True
    assert result.db_dropped is True
    assert result.proxy_block_removed is True
    assert result.instance_folder_removed is True


@pytest.mark.cli_commands
def test_delete_force_cleans_workspace_toml_references(standard_instance_toml, tmp_workspace):
    """delete --force removes compare_pairs and any other workspace.toml refs to instance."""
    with patch("owm.operations._remove_worktrees"), \
         patch("owm.operations._dropdb_archive"), \
         patch("owm.operations._remove_proxy_block"), \
         patch("owm.operations.shutil.rmtree"):
        result = delete_instance(
            instance="feat-789",
            running=False,
            force=True,
            workspace_root=str(tmp_workspace),
            workspace_compare_pairs=[["feat-789", "main"]],
        )
    assert result.workspace_toml_updated is True
    assert ["feat-789", "main"] not in result.remaining_compare_pairs


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------

@pytest.mark.cli_commands
def test_rename_running_instance_hard_error():
    with pytest.raises(Exception) as exc_info:
        rename_instance(instance="feat-789", new_name="pd-789", running=True)
    assert "INSTANCE_RUNNING" in str(exc_info.value) or "stop" in str(exc_info.value).lower()


@pytest.mark.cli_commands
def test_rename_stopped_instance_updates_all_references(standard_instance_toml, tmp_workspace):
    with patch("owm.operations.subprocess.run") as mock_run, \
         patch("owm.operations.shutil.move"):
        mock_run.return_value.returncode = 0
        result = rename_instance(
            instance="feat-789",
            new_name="pd-789",
            running=False,
            workspace_root=str(tmp_workspace),
        )
    assert result.status == "renamed"
    assert result.old_name == "feat-789"
    assert result.new_name == "pd-789"
    assert result.db_renamed is True
    assert result.nginx_block_updated is True
    assert result.port_unchanged is True


@pytest.mark.cli_commands
def test_rename_updates_workspace_toml_compare_pairs(standard_instance_toml, tmp_workspace):
    with patch("owm.operations.subprocess.run") as mock_run, \
         patch("owm.operations.shutil.move"):
        mock_run.return_value.returncode = 0
        result = rename_instance(
            instance="feat-789",
            new_name="pd-789",
            running=False,
            workspace_root=str(tmp_workspace),
            workspace_compare_pairs=[["feat-789", "main"]],
        )
    assert ["pd-789", "main"] in result.remaining_compare_pairs
    assert ["feat-789", "main"] not in result.remaining_compare_pairs


@pytest.mark.cli_commands
def test_rename_updates_proxy_subdomain(standard_instance_toml, tmp_workspace):
    with patch("owm.operations.subprocess.run") as mock_run, \
         patch("owm.operations.shutil.move"):
        mock_run.return_value.returncode = 0
        result = rename_instance(
            instance="feat-789",
            new_name="pd-789",
            running=False,
            workspace_root=str(tmp_workspace),
        )
    assert result.old_url == "http://feat-789.localhost"
    assert result.new_url == "http://pd-789.localhost"


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------

@pytest.mark.cli_commands
def test_logs_default_returns_last_n_lines(tmp_path):
    inst_dir = tmp_path / "instances" / "feat-789"
    inst_dir.mkdir(parents=True)
    (inst_dir / "instance.log").write_text("")
    result = show_logs(instance="feat-789", n=50, follow=False, level=None,
                       workspace_root=str(tmp_path))
    assert len(result.lines) <= 50
    assert result.log_path is not None


@pytest.mark.cli_commands
def test_logs_custom_n(tmp_path):
    inst_dir = tmp_path / "instances" / "feat-789"
    inst_dir.mkdir(parents=True)
    (inst_dir / "instance.log").write_text("")
    result = show_logs(instance="feat-789", n=200, follow=False, level=None,
                       workspace_root=str(tmp_path))
    assert len(result.lines) <= 200


@pytest.mark.cli_commands
def test_logs_level_filter_returns_only_matching_levels(tmp_path):
    inst_dir = tmp_path / "instances" / "feat-789"
    inst_dir.mkdir(parents=True)
    lines = [
        {"level": "INFO", "msg": "started"},
        {"level": "ERROR", "msg": "crash"},
        {"level": "WARNING", "msg": "warn"},
        {"level": "ERROR", "msg": "crash2"},
    ]
    (inst_dir / "instance.log").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n"
    )
    result = show_logs(instance="feat-789", n=100, follow=False, level="ERROR",
                       workspace_root=str(tmp_path))
    for line in result.lines:
        assert line["level"] in ("ERROR", "CRITICAL")


# ---------------------------------------------------------------------------
# db-dump / db-restore
# ---------------------------------------------------------------------------

@pytest.mark.cli_commands
def test_db_dump_default_path():
    with patch("owm.operations._pg_dump"), patch("owm.operations.os.makedirs"):
        result = db_dump(instance="feat-789", out=None, workspace_root="/ws",
                         db_name="odoo19_feat789", pg_port=5432)
    assert result.path.startswith("/ws/_dumps/feat-789/")
    assert result.path.endswith(".dump")


@pytest.mark.cli_commands
def test_db_dump_explicit_path():
    with patch("owm.operations._pg_dump"), patch("owm.operations.os.makedirs"):
        result = db_dump(instance="feat-789", out="/tmp/snapshot.dump", workspace_root="/ws",
                         db_name="odoo19_feat789", pg_port=5432)
    assert result.path == "/tmp/snapshot.dump"


@pytest.mark.cli_commands
def test_db_restore_relative_path_resolves_to_dumps_dir():
    with patch("owm.operations._pg_restore"):
        result = db_restore(
            instance="feat-789",
            path="2026-05-16T09:32.dump",
            workspace_root="/ws",
            db_name="odoo19_feat789",
            pg_port=5432,
            running=False,
        )
    assert result.resolved_path == "/ws/_dumps/feat-789/2026-05-16T09:32.dump"


@pytest.mark.cli_commands
def test_db_restore_absolute_path_used_as_is():
    with patch("owm.operations._pg_restore"):
        result = db_restore(
            instance="feat-789",
            path="/explicit/path/snapshot.dump",
            workspace_root="/ws",
            db_name="odoo19_feat789",
            pg_port=5432,
            running=False,
        )
    assert result.resolved_path == "/explicit/path/snapshot.dump"


@pytest.mark.cli_commands
def test_db_restore_running_instance_hard_error():
    with pytest.raises(Exception) as exc_info:
        db_restore(instance="feat-789", path="snap.dump", workspace_root="/ws",
                   db_name="odoo19_feat789", pg_port=5432, running=True)
    assert "INSTANCE_RUNNING" in str(exc_info.value) or "stop" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@pytest.mark.cli_commands
def test_validate_static_valid_instance():
    result = validate_instance(
        instance="feat-789",
        live=False,
        toml_valid=True,
        port_contested=False,
        branch_format_valid=True,
    )
    assert result.valid is True
    assert result.errors == []


@pytest.mark.cli_commands
def test_validate_static_missing_required_field():
    result = validate_instance(
        instance="feat-789",
        live=False,
        toml_valid=False,
        missing_fields=["database.name"],
    )
    assert result.valid is False
    assert any("database.name" in e for e in result.errors)


@pytest.mark.cli_commands
def test_validate_static_only_no_live_checks():
    """owm validate (no instance materialised yet): static checks only, safe to run."""
    result = validate_instance(
        instance="feat-789",
        live=False,
    )
    assert result.live_checks_run is False


@pytest.mark.cli_commands
def test_validate_live_checks_worktrees_db_venv_proxy():
    result = validate_instance(
        instance="feat-789",
        live=True,
        worktrees_present=True,
        db_reachable=True,
        venv_resolves=True,
        nginx_block_active=True,
    )
    assert result.valid is True
    assert result.live_checks_run is True


# ---------------------------------------------------------------------------
# CWD inference
# ---------------------------------------------------------------------------

@pytest.mark.cwd_inference
def test_cwd_inside_instance_dir_infers_instance():
    result = infer_instance_from_cwd(
        cwd="/ws/instances/feat-789/product-core",
        workspace_root="/ws",
        instances_dir="instances",
    )
    assert result.instance == "feat-789"


@pytest.mark.cwd_inference
def test_cwd_at_workspace_root_infers_no_instance():
    result = infer_instance_from_cwd(
        cwd="/ws",
        workspace_root="/ws",
        instances_dir="instances",
    )
    assert result.instance is None


@pytest.mark.cwd_inference
def test_cwd_inside_instance_root_infers_instance():
    result = infer_instance_from_cwd(
        cwd="/ws/instances/feat-789",
        workspace_root="/ws",
        instances_dir="instances",
    )
    assert result.instance == "feat-789"


@pytest.mark.cwd_inference
def test_explicit_instance_name_overrides_cwd_inference():
    """owm status review-101 from inside feat-789 dir → uses review-101."""
    result = infer_instance_from_cwd(
        cwd="/ws/instances/feat-789/product-core",
        workspace_root="/ws",
        instances_dir="instances",
        explicit_name="review-101",
    )
    assert result.instance == "review-101"


# ---------------------------------------------------------------------------
# Log rotation
# ---------------------------------------------------------------------------

@pytest.mark.log_rotation
def test_rotation_needed_when_line_count_exceeds_20k():
    result = check_rotation_needed(line_count=20001, log_age_days=3, threshold_lines=20000, threshold_days=7)
    assert result.needed is True
    assert result.reason in ("line_count", "lines")


@pytest.mark.log_rotation
def test_rotation_needed_when_age_exceeds_one_week():
    result = check_rotation_needed(line_count=100, log_age_days=8, threshold_lines=20000, threshold_days=7)
    assert result.needed is True
    assert result.reason in ("age", "days")


@pytest.mark.log_rotation
def test_rotation_not_needed_within_thresholds():
    result = check_rotation_needed(line_count=100, log_age_days=3, threshold_lines=20000, threshold_days=7)
    assert result.needed is False


@pytest.mark.log_rotation
def test_local_rotation_discards_log(tmp_path):
    log = tmp_path / "owm.log"
    log.write_text("entry\n")
    result = rotate_log(log_path=str(log), mode="local")
    assert result.discarded is True
    assert result.summarised is False
    assert not log.exists()


@pytest.mark.log_rotation
def test_non_local_rotation_raises_not_implemented(tmp_path):
    log = tmp_path / "owm.log"
    log.write_text("entry\n")
    with pytest.raises(NotImplementedError):
        rotate_log(log_path=str(log), mode="summarise")


# === SPEC GAPS ===
# test_logs_follow_streaming: --follow is specified as a live tail but the interface
#   (generator, async stream, or subprocess handle) is not defined.
# test_delete_checklist_is_configurable: spec says checklist defaults are "lightweight,
#   not blocking" and configurable — configuration location not specced.
# test_rename_updates_archive_references: spec mentions updating _archive/ references;
#   the exact archive directory structure is defined in the Archive section but the
#   rename→archive interaction is only briefly noted.
# test_cwd_workspace_toml_walk_up: spec says "walk up from cwd to find workspace.toml";
#   stopping condition when workspace.toml is absent (filesystem root?) not specified.
