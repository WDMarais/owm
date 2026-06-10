"""
Tests for the script runner: NDJSON format, failure tiers, and compare pairs.
Covers: Script runner section.
"""
import pytest

from owm.scripts import run_script, parse_ndjson_output
from owm.scripts import compare_instances, scaffold_script


# ---------------------------------------------------------------------------
# NDJSON output format
# ---------------------------------------------------------------------------

@pytest.mark.script_runner
def test_ndjson_row_has_case_and_status():
    rows = parse_ndjson_output('{"case": "test_login", "status": "OK"}\n{"case": "test_invoice", "status": "FAIL"}\n')
    assert len(rows) == 2
    assert rows[0] == {"case": "test_login", "status": "OK"}
    assert rows[1] == {"case": "test_invoice", "status": "FAIL"}


@pytest.mark.script_runner
def test_ndjson_status_values_are_ok_fail_warn_none():
    valid_statuses = {"OK", "FAIL", "WARN", "NONE"}
    rows = parse_ndjson_output(
        '{"case": "a", "status": "OK"}\n'
        '{"case": "b", "status": "FAIL"}\n'
        '{"case": "c", "status": "WARN"}\n'
        '{"case": "d", "status": "NONE"}\n'
    )
    for row in rows:
        assert row["status"] in valid_statuses


@pytest.mark.script_runner
def test_ndjson_each_row_is_valid_json():
    raw = '{"case": "test_x", "status": "OK", "result": "success"}\n'
    rows = parse_ndjson_output(raw)
    assert rows[0]["result"] == "success"


# ---------------------------------------------------------------------------
# Row-level failure handling (default)
# ---------------------------------------------------------------------------

@pytest.mark.script_runner
def test_row_level_fail_does_not_abort_remaining_rows():
    result = run_script(
        instance="feat-789",
        script_name="run",
        failure_mode="row_level",
        ndjson_output=(
            '{"case": "a", "status": "OK"}\n'
            '{"case": "b", "status": "FAIL"}\n'
            '{"case": "c", "status": "OK"}\n'
        ),
    )
    assert result.summary.total == 3
    assert result.summary.ok == 2
    assert result.summary.fail == 1
    assert len(result.rows) == 3  # all rows processed


@pytest.mark.script_runner
def test_row_level_summary_counts_all_statuses():
    result = run_script(
        instance="feat-789",
        script_name="run",
        failure_mode="row_level",
        ndjson_output=(
            '{"case": "a", "status": "OK"}\n'
            '{"case": "b", "status": "FAIL"}\n'
            '{"case": "c", "status": "WARN"}\n'
            '{"case": "d", "status": "NONE"}\n'
        ),
    )
    assert result.summary.ok == 1
    assert result.summary.fail == 1
    assert result.summary.warn == 1
    assert result.summary.none == 1
    assert result.summary.total == 4


# ---------------------------------------------------------------------------
# Script-level abort
# ---------------------------------------------------------------------------

@pytest.mark.script_runner
def test_script_abort_signal_stops_early():
    result = run_script(
        instance="feat-789",
        script_name="run",
        failure_mode="row_level",
        ndjson_output=(
            '{"case": "a", "status": "OK"}\n'
            '{"abort": true, "reason": "DB connection failed"}\n'
            '{"case": "c", "status": "OK"}\n'
        ),
    )
    assert result.status == "abort"
    assert result.abort_reason == "DB connection failed"
    assert result.rows_run == 1  # row c not run after abort


@pytest.mark.script_runner
def test_script_abort_surfaces_blocker_reason():
    result = run_script(
        instance="feat-789",
        script_name="run",
        failure_mode="row_level",
        ndjson_output='{"abort": true, "reason": "DB connection failed"}\n',
    )
    assert "DB connection failed" in result.abort_reason


# ---------------------------------------------------------------------------
# Contract-level failure handling
# ---------------------------------------------------------------------------

@pytest.mark.script_runner
def test_contract_acceptable_failure_continues():
    """FAIL on declared-acceptable case → runner continues; does not hard-stop."""
    contract = {
        "acceptable_failures": ["missing_optional_field"],
        "blocking_failures": ["db_write"],
    }
    result = run_script(
        instance="feat-789",
        script_name="run",
        failure_mode="contract",
        contract=contract,
        ndjson_output=(
            '{"case": "missing_optional_field", "status": "FAIL"}\n'
            '{"case": "another_case", "status": "OK"}\n'
        ),
    )
    assert result.status == "ok" or result.status == "partial"
    assert result.summary.total == 2


@pytest.mark.script_runner
def test_contract_blocking_failure_hard_stops():
    contract = {
        "acceptable_failures": ["missing_optional_field"],
        "blocking_failures": ["db_write"],
    }
    result = run_script(
        instance="feat-789",
        script_name="run",
        failure_mode="contract",
        contract=contract,
        ndjson_output=(
            '{"case": "db_write", "status": "FAIL"}\n'
            '{"case": "another_case", "status": "OK"}\n'
        ),
    )
    assert result.status in ("abort", "fail")
    assert result.blocker == "db_write"
    assert result.rows_run == 1  # only db_write ran before hard stop


@pytest.mark.script_runner
def test_contract_violation_surfaced_distinctly():
    """Contract violation (FAIL on blocking case) is distinct from acceptable failure."""
    contract = {
        "acceptable_failures": [],
        "blocking_failures": ["db_write"],
    }
    result = run_script(
        instance="feat-789",
        script_name="run",
        failure_mode="contract",
        contract=contract,
        ndjson_output='{"case": "db_write", "status": "FAIL"}\n',
    )
    assert result.contract_violation is True


# ---------------------------------------------------------------------------
# owm new-script scaffolding
# ---------------------------------------------------------------------------

@pytest.mark.script_runner
def test_scaffold_script_produces_contract_level_template():
    result = scaffold_script(instance="feat-789", script_name="setup")
    assert result.path is not None
    assert "contract" in result.content.lower() or "acceptable_failures" in result.content


# ---------------------------------------------------------------------------
# Compare pairs
# ---------------------------------------------------------------------------

@pytest.mark.script_runner
def test_compare_resolves_target_from_workspace():
    result = compare_instances(
        instance="feat-789",
        workspace_compare_pairs=[["feat-789", "main"]],
    )
    assert result.base_instance == "main"
    assert result.feat_instance == "feat-789"


@pytest.mark.script_runner
def test_compare_ad_hoc_against():
    result = compare_instances(
        instance="feat-789",
        base="main",
        workspace_compare_pairs=[],
    )
    assert result.base_instance == "main"


@pytest.mark.script_runner
def test_compare_expected_change_declared_passes():
    """
    Row 3 changes EXCEPTION→ERROR on feat branch.
    expected_changes declares this as acceptable → pass.
    """
    base_rows  = [
        {"case": "a", "status": "OK"},
        {"case": "b", "status": "OK"},
        {"case": "c", "status": "EXCEPTION"},
        {"case": "d", "status": "ERROR"},
        {"case": "e", "status": "EXCEPTION"},
    ]
    feat_rows  = [
        {"case": "a", "status": "OK"},
        {"case": "b", "status": "OK"},
        {"case": "c", "status": "ERROR"},
        {"case": "d", "status": "ERROR"},
        {"case": "e", "status": "EXCEPTION"},
    ]
    expected_changes = [{"case": "c", "base": "EXCEPTION", "feat": "ERROR"}]
    result = compare_instances(
        instance="feat-789",
        base="main",
        base_rows=base_rows,
        feat_rows=feat_rows,
        expected_changes=expected_changes,
    )
    assert result.status in ("ok", "has_changes")
    assert result.summary.unexpected_changes == 0


@pytest.mark.script_runner
def test_compare_undeclared_change_is_contract_violation():
    """Row differs outside expected_changes → unexpected_changes, surfaced explicitly."""
    base_rows  = [{"case": "x", "status": "OK"}]
    feat_rows  = [{"case": "x", "status": "FAIL"}]
    result = compare_instances(
        instance="feat-789",
        base="main",
        base_rows=base_rows,
        feat_rows=feat_rows,
        expected_changes=[],
    )
    assert result.status == "unexpected_changes"
    assert result.summary.unexpected_changes == 1
    assert result.unexpected[0]["case"] == "x"


@pytest.mark.script_runner
def test_compare_deleted_instance_surfaces_in_status(tmp_path):
    """compare_pair in workspace.toml with one instance deleted → surfaced in status."""
    (tmp_path / "instances" / "feat-789").mkdir(parents=True)
    # "main" instance dir intentionally absent
    result = compare_instances(
        instance="feat-789",
        base="main",
        workspace_root=str(tmp_path),
    )
    assert result.status == "error" or result.error is not None
    assert "not found" in (result.error or "").lower() or result.missing_instance == "main"


@pytest.mark.script_runner
def test_compare_symmetric_either_instance_can_initiate():
    """compare pair is symmetric — initiating from either end should work."""
    result_from_feat = compare_instances(
        instance="feat-789",
        workspace_compare_pairs=[["feat-789", "main"]],
        base_rows=[{"case": "a", "status": "OK"}],
        feat_rows=[{"case": "a", "status": "OK"}],
    )
    result_from_main = compare_instances(
        instance="main",
        workspace_compare_pairs=[["feat-789", "main"]],
        base_rows=[{"case": "a", "status": "OK"}],
        feat_rows=[{"case": "a", "status": "OK"}],
    )
    # Both should resolve the pair without error
    assert result_from_feat.status in ("ok", "has_changes", "unexpected_changes")
    assert result_from_main.status in ("ok", "has_changes", "unexpected_changes")


# === SPEC GAPS ===
# test_script_abort_via_exit_code: spec says "special row or exit code" for abort signal;
#   both mechanisms are mentioned but which takes precedence is not specced.
# test_contract_declaration_location_in_script: the contract declaration format within
#   the script file is not fully specced (JSON header? special NDJSON row?).
# test_compare_ndjson_written_for_both_instances: spec says ndjson_base and ndjson_feat
#   paths returned; file retention policy (how long kept) not specced.
