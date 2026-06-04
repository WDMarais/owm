"""
Tests for workspace.toml and instance.toml config parsing.
Covers: Config schemas, Requirements patching sections.
"""
import pytest

from owm.config import parse_workspace_config, parse_instance_config, load_instance_config
from owm.config import ConfOwnership
from owm.config import WorkspaceConfig, InstanceConfig, RepoSpec, ClusterConfig
from owm.config import WorkspaceDefaults, WorkspaceRepo
from owm.errors import OwmError, ConfigError, NOT_FOUND

# ---------------------------------------------------------------------------
# Workspace.toml — integration: parse full valid config
# ---------------------------------------------------------------------------

@pytest.mark.config_schemas
def test_parse_workspace_config_full_valid():
    toml = """
[repos]
odoo            = {path = "git@github.com:odoo/odoo.git", has_addons = true}
product-core    = {path = "git@bitbucket.org:org/product-core.git", has_addons = true}
customer-config = {path = "git@bitbucket.org:org/customer-config.git", has_addons = true}
scripts         = {path = "git@bitbucket.org:org/scripts.git"}

[clusters]
"19" = {pg_version = "16", port = 5432}
"12" = {pg_version = "12", port = 5433}

[defaults]
instances_dir       = "instances"
http_port_range     = [8100, 8299]
owm_port_range      = [8090, 8099]
workers             = 2
sync_warn_hours     = 72
eviction_threshold  = 10
template_warn_days  = 30

[patches]
"19" = ["requirements_patches/odoo19_fix.txt"]
"12" = ["requirements_patches/odoo12_compat.txt"]

[compare_pairs]
pairs = [["feat-789", "main"]]

[scripts]
scripts_dir = "scripts/workspace"

[proxy]
domain_suffix = "localhost"
"""
    config = parse_workspace_config(toml)
    assert config.repos["odoo"].path == "git@github.com:odoo/odoo.git"
    assert config.repos["scripts"].path == "git@bitbucket.org:org/scripts.git"
    assert config.repos["odoo"].has_addons is True
    assert config.repos["scripts"].has_addons is False
    assert config.clusters["19"].pg_version == "16"
    assert config.clusters["19"].port == 5432
    assert config.clusters["12"].port == 5433
    assert config.defaults.http_port_range == [8100, 8299]
    assert config.defaults.owm_port_range == [8090, 8099]
    assert config.defaults.workers == 2
    assert config.defaults.sync_warn_hours == 72
    assert config.defaults.eviction_threshold == 10
    assert config.defaults.template_warn_days == 30
    assert config.patches["19"] == ["requirements_patches/odoo19_fix.txt"]
    assert config.patches["12"] == ["requirements_patches/odoo12_compat.txt"]
    assert config.compare_pairs == [["feat-789", "main"]]
    assert config.proxy.domain_suffix == "localhost"


@pytest.mark.config_schemas
def test_parse_workspace_config_minimal_valid():
    """Only required fields — no patches, no compare_pairs, no proxy."""
    toml = """
[repos]
odoo = "git@github.com:odoo/odoo.git"

[clusters]
"19" = {pg_version = "16", port = 5432}
"""
    config = parse_workspace_config(toml)
    assert "odoo" in config.repos
    assert config.patches == {}
    assert config.compare_pairs == []


@pytest.mark.config_schemas
def test_parse_workspace_config_missing_repos_raises():
    toml = """
[clusters]
"19" = {pg_version = "16", port = 5432}
"""
    with pytest.raises(Exception) as exc_info:  # ValidationError or equivalent
        parse_workspace_config(toml)
    assert not isinstance(exc_info.value, NotImplementedError), "stub not wired up"


@pytest.mark.config_schemas
def test_parse_workspace_config_missing_clusters_raises():
    toml = """
[repos]
odoo = "git@github.com:odoo/odoo.git"
"""
    with pytest.raises(Exception) as exc_info:
        parse_workspace_config(toml)
    assert not isinstance(exc_info.value, NotImplementedError), "stub not wired up"



@pytest.mark.config_schemas
def test_parse_workspace_config_invalid_port_range_type_raises():
    toml = """
[repos]
odoo = "git@github.com:odoo/odoo.git"

[clusters]
"19" = {pg_version = "16", port = 5432}

[defaults]
http_port_range = "not-a-list"
"""
    with pytest.raises(Exception) as exc_info:
        parse_workspace_config(toml)
    assert not isinstance(exc_info.value, NotImplementedError), "stub not wired up"


@pytest.mark.config_schemas
def test_parse_workspace_config_defaults_applied_when_absent():
    """Absent [defaults] section uses sensible defaults, not None."""
    toml = """
[repos]
odoo = "git@github.com:odoo/odoo.git"

[clusters]
"19" = {pg_version = "16", port = 5432}
"""
    config = parse_workspace_config(toml)
    assert config.defaults.http_port_range == [8100, 8299]
    assert config.defaults.workers == 2
    assert config.defaults.eviction_threshold == 10
    assert config.defaults.template_warn_days == 30


# ---------------------------------------------------------------------------
# Repo spec string parsing: "branch:base+flags"
# ---------------------------------------------------------------------------

from owm.config import parse_repo_spec


@pytest.mark.config_schemas
def test_repo_spec_owned_branch():
    spec = parse_repo_spec("feat-789-dev:dev")
    assert spec.branch == "feat-789-dev"
    assert spec.base == "dev"
    assert spec.shared is False
    assert spec.readonly is False
    assert spec.assert_exists is False


@pytest.mark.config_schemas
def test_repo_spec_shared():
    spec = parse_repo_spec("19.0:shared")
    assert spec.branch == "19.0"
    assert spec.shared is True
    assert spec.readonly is False


@pytest.mark.config_schemas
def test_repo_spec_readonly():
    spec = parse_repo_spec("feat-789-dev:dev+readonly")
    assert spec.branch == "feat-789-dev"
    assert spec.base == "dev"
    assert spec.readonly is True
    assert spec.shared is False
    assert spec.assert_exists is False


@pytest.mark.config_schemas
def test_repo_spec_exists_flag():
    spec = parse_repo_spec("feat-789-dev:dev+exists")
    assert spec.branch == "feat-789-dev"
    assert spec.assert_exists is True
    assert spec.readonly is False


@pytest.mark.config_schemas
def test_repo_spec_multiple_flags():
    spec = parse_repo_spec("reviews/feat-789:dev+readonly")
    assert spec.branch == "reviews/feat-789"
    assert spec.base == "dev"
    assert spec.readonly is True


@pytest.mark.config_schemas
def test_repo_spec_exists_and_readonly():
    spec = parse_repo_spec("feat-789-dev:dev+exists+readonly")
    assert spec.assert_exists is True
    assert spec.readonly is True


@pytest.mark.config_schemas
def test_repo_spec_bare_branch_no_colon():
    # No colon → no base, matching owm's tolerant form (e.g. odoo = "12.0")
    spec = parse_repo_spec("12.0")
    assert spec.branch == "12.0"
    assert spec.base is None
    assert spec.shared is False
    assert spec.readonly is False
    assert spec.assert_exists is False
    assert spec.create is False


@pytest.mark.config_schemas
def test_repo_spec_bare_branch_with_flags_no_colon():
    spec = parse_repo_spec("feature-x+readonly")
    assert spec.branch == "feature-x"
    assert spec.base is None
    assert spec.shared is False
    assert spec.readonly is True


# ---------------------------------------------------------------------------
# Repo spec inline-table parsing: {branch = "...", base = "...", flags...}
# ---------------------------------------------------------------------------

@pytest.mark.config_schemas
def test_repo_spec_inline_table_owned():
    spec = parse_repo_spec({"branch": "feat-789-dev", "base": "dev"})
    assert spec.branch == "feat-789-dev"
    assert spec.base == "dev"
    assert spec.shared is False
    assert spec.readonly is False
    assert spec.assert_exists is False


@pytest.mark.config_schemas
def test_repo_spec_inline_table_shared():
    spec = parse_repo_spec({"branch": "19.0", "shared": True})
    assert spec.branch == "19.0"
    assert spec.shared is True
    assert spec.base is None


@pytest.mark.config_schemas
def test_repo_spec_inline_table_readonly():
    spec = parse_repo_spec({"branch": "feat-789-dev", "base": "main", "readonly": True})
    assert spec.readonly is True
    assert spec.shared is False
    assert spec.assert_exists is False


@pytest.mark.config_schemas
def test_repo_spec_inline_table_all_flags():
    spec = parse_repo_spec({"branch": "feat-789-dev", "base": "dev", "readonly": True, "exists": True})
    assert spec.readonly is True
    assert spec.assert_exists is True


@pytest.mark.config_schemas
def test_parse_instance_config_accepts_inline_table_repos():
    toml = """
[repos]
odoo = {branch = "19.0", shared = true}
product_core = {branch = "feat-789-dev", base = "main", readonly = true}

[database]
name = "feat_789"
pg_port = 5432

[server]
http_port = 8142
gevent_port = 8143
"""
    from owm.config import parse_instance_config
    conf = parse_instance_config(toml)
    assert conf.repos["odoo"].shared is True
    assert conf.repos["odoo"].branch == "19.0"
    assert conf.repos["product_core"].readonly is True
    assert conf.repos["product_core"].base == "main"


# ---------------------------------------------------------------------------
# instance.toml — integration: parse full valid config
# ---------------------------------------------------------------------------

@pytest.mark.config_schemas
def test_parse_instance_config_full_valid():
    toml = """
[repos]
odoo            = "19.0:shared"
product-core    = "feat-789-dev:dev"
customer-config = "feat-789-dev:dev+exists"
scripts         = "reviews/feat-789:dev+readonly"

[database]
name     = "odoo19_feat789"
pg_port  = 5432
template = "odoo19_base"

[server]
http_port    = 8142
gevent_port  = 8143
workers      = 2

[install]
modules = ["my_module", "other_module"]

[python]
version = "3.12"

[scripts]
default     = "run"
scripts_dir = "scripts/reviews/PD-789"

[scripts.runners]
setup   = {file = "setup.py",   type = "shell"}
run     = {file = "run.py",     type = "shell"}
compare = {file = "compare.py", type = "plain"}

[scripts.compare]
target = "main"

[template]
sync_opt_in = false
"""
    config = parse_instance_config(toml)
    assert config.repos["odoo"].shared is True
    assert config.repos["product-core"].branch == "feat-789-dev"
    assert config.repos["customer-config"].assert_exists is True
    assert config.repos["scripts"].readonly is True
    assert config.database.name == "odoo19_feat789"
    assert config.database.pg_port == 5432
    assert config.database.template == "odoo19_base"
    assert config.server.http_port == 8142
    assert config.server.gevent_port == 8143
    assert config.server.gevent_port == config.server.http_port + 1
    assert config.server.workers == 2
    assert config.install.modules == ["my_module", "other_module"]
    assert config.python.version == "3.12"
    assert config.scripts.default == "run"
    assert config.scripts.runners["setup"].file == "setup.py"
    assert config.scripts.runners["setup"].type == "shell"
    assert config.scripts.runners["compare"].type == "plain"
    assert config.scripts.compare.target == "main"
    assert config.template.sync_opt_in is False


@pytest.mark.config_schemas
def test_parse_instance_config_gevent_port_must_be_http_plus_one():
    """gevent_port = http_port + 1 is an invariant; mismatched pair is invalid."""
    toml = """
[repos]
odoo = "19.0:shared"

[database]
name    = "odoo19_feat789"
pg_port = 5432

[server]
http_port   = 8142
gevent_port = 8150
"""
    with pytest.raises(Exception) as exc_info:
        parse_instance_config(toml)
    assert not isinstance(exc_info.value, NotImplementedError), "stub not wired up"


@pytest.mark.config_schemas
def test_parse_instance_config_gevent_port_derived_when_absent():
    """A toml with http_port but no gevent_port (e.g. an adopted owm instance) derives
    gevent_port = http_port + 1 rather than defaulting to 0 or erroring."""
    toml = """
[repos]
odoo = "19.0:shared"

[database]
name    = "odoo19_feat789"
pg_port = 5432

[server]
http_port = 8142
"""
    config = parse_instance_config(toml)
    assert config.server.gevent_port == 8143


@pytest.mark.config_schemas
def test_parse_instance_config_no_template_field():
    """template field in [database] is optional; absent means blank slate."""
    toml = """
[repos]
odoo = "19.0:shared"

[database]
name    = "odoo19_feat789"
pg_port = 5432

[server]
http_port   = 8142
gevent_port = 8143
"""
    config = parse_instance_config(toml)
    assert config.database.template is None


@pytest.mark.config_schemas
def test_parse_instance_config_no_python_version():
    """python.version is optional; absent means inferred from Odoo branch."""
    toml = """
[repos]
odoo = "19.0:shared"

[database]
name    = "odoo19_feat789"
pg_port = 5432

[server]
http_port   = 8142
gevent_port = 8143
"""
    config = parse_instance_config(toml)
    assert config.python is None or config.python.version is None


@pytest.mark.config_schemas
def test_parse_instance_config_missing_database_raises():
    toml = """
[repos]
odoo = "19.0:shared"

[server]
http_port   = 8142
gevent_port = 8143
"""
    with pytest.raises(Exception) as exc_info:
        parse_instance_config(toml)
    assert not isinstance(exc_info.value, NotImplementedError), "stub not wired up"


# ---------------------------------------------------------------------------
# load_instance_config — the by-name loader (path guard + open + parse)
# ---------------------------------------------------------------------------

_VALID_INSTANCE_TOML = """
[repos]
odoo = "19.0:shared"

[database]
name    = "feat_789"
pg_port = 5432

[server]
http_port = 8142
"""


def _write_instance(workspace_root, instance, toml):
    inst_dir = workspace_root / "instances" / instance
    inst_dir.mkdir(parents=True)
    (inst_dir / "instance.toml").write_text(toml)


@pytest.mark.config_schemas
def test_load_instance_config_reads_and_parses(tmp_path):
    _write_instance(tmp_path, "feat-789", _VALID_INSTANCE_TOML)
    conf = load_instance_config("feat-789", str(tmp_path))
    assert conf.database.name == "feat_789"
    assert conf.server.gevent_port == 8143


@pytest.mark.config_schemas
def test_load_instance_config_missing_instance_raises_not_found(tmp_path):
    with pytest.raises(OwmError) as exc_info:
        load_instance_config("ghost", str(tmp_path))
    assert exc_info.value.code == NOT_FOUND


@pytest.mark.config_schemas
def test_load_instance_config_malformed_raises_config_error(tmp_path):
    _write_instance(tmp_path, "broken", "this is = not [valid toml")
    with pytest.raises(ConfigError):
        load_instance_config("broken", str(tmp_path))


@pytest.mark.config_schemas
def test_parse_instance_config_missing_server_raises():
    toml = """
[repos]
odoo = "19.0:shared"

[database]
name    = "odoo19_feat789"
pg_port = 5432
"""
    with pytest.raises(Exception) as exc_info:
        parse_instance_config(toml)
    assert not isinstance(exc_info.value, NotImplementedError), "stub not wired up"


# ---------------------------------------------------------------------------
# Requirements patching
# ---------------------------------------------------------------------------

from owm.venv import resolve_patches


@pytest.mark.config_schemas
@pytest.mark.requirements_patching
def test_resolve_patches_returns_files_for_matching_version():
    patches = {
        "12.0": ["requirements_patches/odoo12_compat.txt"],
        "19.0": ["requirements_patches/odoo19_fix.txt"],
    }
    result = resolve_patches(odoo_version="19.0", patches=patches)
    assert result == ["requirements_patches/odoo19_fix.txt"]


@pytest.mark.config_schemas
@pytest.mark.requirements_patching
def test_resolve_patches_returns_empty_for_unmatched_version():
    patches = {
        "12.0": ["requirements_patches/odoo12_compat.txt"],
    }
    result = resolve_patches(odoo_version="17.0", patches=patches)
    assert result == []


@pytest.mark.config_schemas
@pytest.mark.requirements_patching
def test_resolve_patches_returns_multiple_files():
    patches = {
        "19" : ["requirements_patches/fix1.txt", "requirements_patches/fix2.txt"],
    }
    result = resolve_patches(odoo_version="19", patches=patches)
    assert result == ["requirements_patches/fix1.txt", "requirements_patches/fix2.txt"]


@pytest.mark.config_schemas
@pytest.mark.requirements_patching
def test_resolve_patches_major_version_key_matches():
    """workspace.toml uses "19" as key (major version string), not "19.0"."""
    patches = {
        "19": ["requirements_patches/odoo19_fix.txt"],
    }
    result = resolve_patches(odoo_version="19", patches=patches)
    assert result == ["requirements_patches/odoo19_fix.txt"]


# === SPEC GAPS ===
# test_parse_instance_config_repos_required: spec implies at minimum one repo, but does not
#   state whether an empty [repos] table is a hard error.
# test_repo_spec_shared_flag_implies_no_per_instance_worktree: parsing captures the flag,
#   but the downstream implication (no worktree created) belongs in lifecycle tests.
# test_parse_workspace_config_compare_pairs_format: spec shows pairs as [["a","b"]], but
#   does not specify what happens if a pair has >2 elements or only 1 element.
# test_resolve_patches_version_string_normalisation: it is unclear whether "19.0" and "19"
#   should match the same patch key; spec shows both forms in different examples.


# ---------------------------------------------------------------------------
# Structured config errors: parse failures raise ConfigError (OWM_CONFIG_INVALID)
# with a message naming the offending field, not a leaked TypeError/KeyError.
# ---------------------------------------------------------------------------

from owm.errors import ConfigError, OWM_CONFIG_INVALID


@pytest.mark.config_schemas
def test_malformed_toml_raises_config_error():
    with pytest.raises(ConfigError) as exc:
        parse_instance_config("this is not = valid toml [[[")
    assert exc.value.code == OWM_CONFIG_INVALID


@pytest.mark.config_schemas
def test_script_runner_string_shorthand_raises_named_config_error():
    # owm writes runners as bare filename strings; re-owm requires {file, type}.
    # The error must name the runner, not leak "string indices must be integers".
    toml = """
[database]
name = "x"
pg_port = 5432
[server]
http_port = 8100
[scripts.runners]
test = "run.py"
"""
    with pytest.raises(ConfigError) as exc:
        parse_instance_config(toml)
    assert exc.value.code == OWM_CONFIG_INVALID
    assert "scripts.runners" in str(exc.value)
    assert "test" in str(exc.value)


@pytest.mark.config_schemas
def test_colonless_repo_spec_parses_as_bare_branch():
    # owm allows a bare branch string with no base; re-owm now accepts it too,
    # treating the whole string as the branch with no base (no colon required).
    toml = """
[repos]
product-core = "some_branch_no_colon"
[database]
name = "x"
pg_port = 5432
[server]
http_port = 8100
"""
    cfg = parse_instance_config(toml)
    spec = cfg.repos["product-core"]
    assert spec.branch == "some_branch_no_colon"
    assert spec.base is None
    assert spec.shared is False


# ---------------------------------------------------------------------------
# instance_config_path — missing-instance guard
# ---------------------------------------------------------------------------

@pytest.mark.config_schemas
def test_instance_config_path_returns_path_for_existing_instance(tmp_path):
    from owm.config import instance_config_path
    inst = tmp_path / "instances" / "feat-1"
    inst.mkdir(parents=True)
    (inst / "instance.toml").write_text("")
    assert instance_config_path("feat-1", str(tmp_path)) == str(inst / "instance.toml")


@pytest.mark.config_schemas
def test_instance_config_path_raises_not_found_for_missing_instance(tmp_path):
    from owm.config import instance_config_path
    from owm.errors import OwmError
    with pytest.raises(OwmError) as exc:
        instance_config_path("ghost", str(tmp_path))
    assert exc.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# ConfOwnership — the marker that gates instance.conf regeneration. A managed
# conf may be regenerated, a manual one is left alone, and an unmarked one is a
# refusal (so a hand-written conf is never clobbered without an explicit choice).
# ---------------------------------------------------------------------------

@pytest.mark.config_schemas
def test_conf_ownership_detect_managed(tmp_path):
    p = tmp_path / "instance.conf"
    p.write_text(f"{ConfOwnership.MANAGED} — change to manual to take ownership\n[options]\n")
    assert ConfOwnership.detect(str(p)) is ConfOwnership.MANAGED


@pytest.mark.config_schemas
def test_conf_ownership_detect_manual(tmp_path):
    p = tmp_path / "instance.conf"
    p.write_text(f"{ConfOwnership.MANUAL}\n[options]\nhttp_port = 9999\n")
    assert ConfOwnership.detect(str(p)) is ConfOwnership.MANUAL


@pytest.mark.config_schemas
def test_conf_ownership_detect_absent_marker_is_none(tmp_path):
    p = tmp_path / "instance.conf"
    p.write_text("[options]\nhttp_port = 8069\n")
    assert ConfOwnership.detect(str(p)) is None
