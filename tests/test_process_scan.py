"""
Tests for the Odoo-process scan and the port-holder classifier.
Covers: Status surface — odoo-ps (the one cmdline walk + the --config fingerprint).
"""
from unittest.mock import patch, MagicMock

import pytest

from owm.instance import scan_odoo_processes, classify_port_holder


def _proc(pid, cmdline):
    p = MagicMock()
    p.info = {"pid": pid, "cmdline": cmdline}
    return p


# instances_root("/ws") == "/ws/instances"; an owm-shaped --config lives directly
# under it (one instance dir deep), so this path fingerprints as instance feat-789.
OURS = ["python", "/x/odoo-bin", "--config", "/ws/instances/feat-789/instance.conf"]
FOREIGN = ["python", "/opt/odoo/odoo-bin", "-c", "/etc/odoo/odoo.conf"]
NON_ODOO = ["nginx", "-g", "daemon off;"]


@pytest.mark.process_scan
def test_scan_splits_owm_shaped_from_foreign():
    procs = [_proc(100, OURS), _proc(200, FOREIGN), _proc(300, NON_ODOO),
             _proc(400, None), _proc(500, [])]
    with patch("owm.instance.psutil.process_iter", return_value=procs):
        result = scan_odoo_processes("/ws")
    assert result["owm_shaped"] == [{"pid": 100, "instance": "feat-789"}]
    assert result["foreign"] == [{"pid": 200, "cmdline": " ".join(FOREIGN)}]


@pytest.mark.process_scan
def test_scan_does_not_misfile_non_odoo_as_foreign():
    with patch("owm.instance.psutil.process_iter", return_value=[_proc(300, NON_ODOO)]):
        result = scan_odoo_processes("/ws")
    assert result == {"owm_shaped": [], "foreign": []}


@pytest.mark.process_scan
def test_classify_owm_shaped_is_probable_orphan():
    assert classify_port_holder(" ".join(OURS), "/ws") == "probable_orphan"


@pytest.mark.process_scan
def test_classify_foreign_odoo():
    assert classify_port_holder(" ".join(FOREIGN), "/ws") == "foreign_odoo"


@pytest.mark.process_scan
def test_classify_non_odoo_is_probable_squatter():
    assert classify_port_holder(" ".join(NON_ODOO), "/ws") == "probable_squatter"


@pytest.mark.process_scan
def test_classify_none_cmdline_is_probable_squatter():
    # find_conflicting_process returns cmdline=None under AccessDenied — must not crash.
    assert classify_port_holder(None, "/ws") == "probable_squatter"
