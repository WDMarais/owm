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
    # The script writes its NDJSON to $NDJSON_OUT and prints a run log to stdout;
    # owm consumes the file, not stdout.
    def fake_execute(inst, script, ws, ndjson_out=None):
        with open(ndjson_out, "w") as f:
            f.write(output)
        return "run complete\n"
    with patch("owm.api.execute_script", side_effect=fake_execute):
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


def test_run_script_tallies_file_and_surfaces_run_log(tmp_workspace):
    """NDJSON comes from the results file; stdout is the run log, shown as-is."""
    def fake_execute(inst, script, ws, ndjson_out=None):
        with open(ndjson_out, "w") as f:
            f.write('{"case": "x", "status": "OK"}\n')
        return "✓ did a thing\nall done\n"
    with patch("owm.api.execute_script", side_effect=fake_execute):
        r = run_instance_script("feat-1", str(tmp_workspace), "smoke")
    assert r["summary"]["total"] == 1  # tallied from the file
    assert r["output"] == "✓ did a thing\nall done\n"  # run log, verbatim
    assert open(r["log_path"]).read() == "✓ did a thing\nall done\n"  # log persisted


def test_run_script_no_ndjson_is_clean_zero(tmp_workspace):
    """NDJSON is opt-in: a script that writes none is a clean 0-row run, not a failure."""
    with patch("owm.api.execute_script", side_effect=lambda *a, **k: "just printing\n"):
        r = run_instance_script("feat-1", str(tmp_workspace), "smoke")
    assert r["status"] == "ok"
    assert r["summary"]["total"] == 0
    assert os.path.exists(r["ndjson_path"])  # empty file created for the latest pointer
