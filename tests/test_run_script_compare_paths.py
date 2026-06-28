"""
End-to-end proof that run-script and compare agree on NDJSON paths.

These do NOT mock compare_instances (unlike test_mcp_surface), so they exercise
the real file handoff: run_instance_script writes the dumps, compare_instance
reads them back and diffs for real. Guards the regression where run-script wrote
<script>-latest.ndjson while compare read latest.ndjson and found nothing.
"""
from unittest.mock import patch

from owm.api import run_instance_script, compare_instance


FEAT_OUT = '{"case": "login", "status": "OK"}\n{"case": "invoice", "status": "OK"}\n'
BASE_OUT = '{"case": "login", "status": "OK"}\n{"case": "invoice", "status": "FAIL"}\n'


def _run(instance, output, tmp_workspace):
    with patch("owm.api.execute_script", return_value=output):
        return run_instance_script(instance, str(tmp_workspace), "smoke")


def test_run_script_writes_both_per_script_and_latest_pointer(tmp_workspace):
    result = _run("feat-1", FEAT_OUT, tmp_workspace)
    dumps = tmp_workspace / "_dumps" / "feat-1"
    assert (dumps / "smoke-latest.ndjson").read_text() == FEAT_OUT
    assert (dumps / "latest.ndjson").read_text() == FEAT_OUT
    assert result["ndjson_path"].endswith("smoke-latest.ndjson")


def test_compare_reads_latest_pointer_run_script_wrote(tmp_workspace):
    _run("feat-1", FEAT_OUT, tmp_workspace)
    _run("base-1", BASE_OUT, tmp_workspace)

    result = compare_instance("feat-1", str(tmp_workspace), base="base-1")
    assert result["status"] == "unexpected_changes"
    assert any(u["case"] == "invoice" for u in result["unexpected"])


def test_compare_can_target_a_named_script(tmp_workspace):
    _run("feat-1", FEAT_OUT, tmp_workspace)
    _run("base-1", BASE_OUT, tmp_workspace)

    result = compare_instance("feat-1", str(tmp_workspace), base="base-1", script="smoke")
    assert result["status"] == "unexpected_changes"
    assert any(u["case"] == "invoice" for u in result["unexpected"])
