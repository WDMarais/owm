"""
End-to-end proof that run-script and compare agree on NDJSON paths.

These do NOT mock compare_instances (unlike test_mcp_surface), so they exercise
the real file handoff: run_instance_script writes the dumps, compare_instance
reads them back and diffs for real. Guards the regression where run-script wrote
<script>-latest.ndjson while compare read latest.ndjson and found nothing.
"""
import os
from unittest.mock import patch

from owm.api import run_instance_script, compare_instance


FEAT_OUT = '{"case": "login", "status": "OK"}\n{"case": "invoice", "status": "OK"}\n'
BASE_OUT = '{"case": "login", "status": "OK"}\n{"case": "invoice", "status": "FAIL"}\n'


def _run(instance, output, tmp_workspace):
    with patch("owm.api.execute_script", return_value=output):
        return run_instance_script(instance, str(tmp_workspace), "smoke")


def test_run_script_writes_timestamped_record_and_latest_symlinks(tmp_workspace):
    result = _run("feat-1", FEAT_OUT, tmp_workspace)
    dumps = tmp_workspace / "_dumps" / "feat-1"

    # ndjson_path is the immutable timestamped record, not a latest pointer
    assert os.path.basename(result["ndjson_path"]).startswith("smoke-")
    assert result["ndjson_path"].endswith(".ndjson")
    assert "latest" not in os.path.basename(result["ndjson_path"])
    assert os.path.realpath(result["ndjson_path"]) == str(dumps / os.path.basename(result["ndjson_path"]))

    # both latest pointers are symlinks resolving to that record's content
    assert (dumps / "smoke-latest.ndjson").is_symlink()
    assert (dumps / "latest.ndjson").is_symlink()
    assert (dumps / "smoke-latest.ndjson").read_text() == FEAT_OUT
    assert (dumps / "latest.ndjson").read_text() == FEAT_OUT


def test_new_run_repoints_latest_keeping_prior_record(tmp_workspace):
    first = _run("feat-1", FEAT_OUT, tmp_workspace)
    second = _run("feat-1", BASE_OUT, tmp_workspace)
    dumps = tmp_workspace / "_dumps" / "feat-1"

    # the older record is preserved verbatim; latest follows the newest run
    assert first["ndjson_path"] != second["ndjson_path"]
    assert open(first["ndjson_path"]).read() == FEAT_OUT
    assert (dumps / "latest.ndjson").read_text() == BASE_OUT


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


def test_run_script_surfaces_plain_output_and_tallies_only_rows(tmp_workspace):
    mixed = '✓ did a thing\n{"case": "x", "status": "OK"}\nall done\n'
    with patch("owm.api.execute_script", return_value=mixed):
        r = run_instance_script("feat-1", str(tmp_workspace), "smoke")
    assert r["summary"]["total"] == 1  # only the NDJSON row is tallied
    assert r["output"] == ["✓ did a thing", "all done"]  # prints surfaced
