"""
Tests for workspace.toml and instance.toml config parsing.
Covers: Config schemas, Requirements patching sections.
"""
import pytest

# TODO: from owm.config import parse_workspace_config, parse_instance_config
# TODO: from owm.config import WorkspaceConfig, InstanceConfig, RepoSpec, ClusterConfig
# TODO: from owm.config import WorkspaceDefaults, RepoMeta

def parse_workspace_config(*args, **kwargs):
    raise NotImplementedError

def parse_instance_config(*args, **kwargs):
    raise NotImplementedError

# ---------------------------------------------------------------------------
# Workspace.toml — integration: parse full valid config
# ---------------------------------------------------------------------------

@pytest.mark.config_schemas
def test_parse_workspace_config_full_valid():
    toml = """
[repos]
odoo            = "git@github.com:odoo/odoo.git"
product-core    = "git@bitbucket.org:org/product-core.git"
customer-config = "git@bitbucket.org:org/customer-config.git"
scripts         = "git@bitbucket.org:org/scripts.git"

[repos.meta]
odoo.has_addons            = true
product-core.has_addons    = true
customer-config.has_addons = true
scripts.has_addons         = false

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
    config = parse_workspace_config(toml)  # TODO: wire up
    assert config.repos["odoo"] == "git@github.com:odoo/odoo.git"
    assert config.repos["scripts"] == "git@bitbucket.org:org/scripts.git"
    assert config.repos_meta["odoo"].has_addons is True
    assert config.repos_meta["scripts"].has_addons is False
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
    config = parse_workspace_config(toml)  # TODO: wire up
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
        parse_workspace_config(toml)  # TODO: wire up
    assert not isinstance(exc_info.value, NotImplementedError), "stub not wired up"


@pytest.mark.config_schemas
def test_parse_workspace_config_missing_clusters_raises():
    toml = """
[repos]
odoo = "git@github.com:odoo/odoo.git"
"""
    with pytest.raises(Exception) as exc_info:
        parse_workspace_config(toml)  # TODO: wire up
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
        parse_workspace_config(toml)  # TODO: wire up
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
    config = parse_workspace_config(toml)  # TODO: wire up
    assert config.defaults.http_port_range == [8100, 8299]
    assert config.defaults.workers == 2
    assert config.defaults.eviction_threshold == 10
    assert config.defaults.template_warn_days == 30


# ---------------------------------------------------------------------------
# Repo spec string parsing: "branch:base+flags"
# ---------------------------------------------------------------------------

# TODO: from owm.config import parse_repo_spec
def parse_repo_spec(*args, **kwargs):
    raise NotImplementedError


@pytest.mark.config_schemas
def test_repo_spec_owned_branch():
    spec = parse_repo_spec("feat-789-dev:dev")  # TODO: wire up
    assert spec.branch == "feat-789-dev"
    assert spec.base == "dev"
    assert spec.shared is False
    assert spec.readonly is False
    assert spec.exists is False


@pytest.mark.config_schemas
def test_repo_spec_shared():
    spec = parse_repo_spec("19.0:shared")  # TODO: wire up
    assert spec.branch == "19.0"
    assert spec.shared is True
    assert spec.readonly is False


@pytest.mark.config_schemas
def test_repo_spec_readonly():
    spec = parse_repo_spec("feat-789-dev:dev+readonly")  # TODO: wire up
    assert spec.branch == "feat-789-dev"
    assert spec.base == "dev"
    assert spec.readonly is True
    assert spec.shared is False
    assert spec.exists is False


@pytest.mark.config_schemas
def test_repo_spec_exists_flag():
    spec = parse_repo_spec("feat-789-dev:dev+exists")  # TODO: wire up
    assert spec.branch == "feat-789-dev"
    assert spec.exists is True
    assert spec.readonly is False


@pytest.mark.config_schemas
def test_repo_spec_multiple_flags():
    spec = parse_repo_spec("reviews/feat-789:dev+readonly")  # TODO: wire up
    assert spec.branch == "reviews/feat-789"
    assert spec.base == "dev"
    assert spec.readonly is True


@pytest.mark.config_schemas
def test_repo_spec_exists_and_readonly():
    spec = parse_repo_spec("feat-789-dev:dev+exists+readonly")  # TODO: wire up
    assert spec.exists is True
    assert spec.readonly is True


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
    config = parse_instance_config(toml)  # TODO: wire up
    assert config.repos["odoo"].shared is True
    assert config.repos["product-core"].branch == "feat-789-dev"
    assert config.repos["customer-config"].exists is True
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
        parse_instance_config(toml)  # TODO: wire up
    assert not isinstance(exc_info.value, NotImplementedError), "stub not wired up"


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
    config = parse_instance_config(toml)  # TODO: wire up
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
    config = parse_instance_config(toml)  # TODO: wire up
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
        parse_instance_config(toml)  # TODO: wire up
    assert not isinstance(exc_info.value, NotImplementedError), "stub not wired up"


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
        parse_instance_config(toml)  # TODO: wire up
    assert not isinstance(exc_info.value, NotImplementedError), "stub not wired up"


# ---------------------------------------------------------------------------
# Requirements patching
# ---------------------------------------------------------------------------

# TODO: from owm.venv import resolve_patches
def resolve_patches(*args, **kwargs):
    raise NotImplementedError


@pytest.mark.config_schemas
@pytest.mark.requirements_patching
def test_resolve_patches_returns_files_for_matching_version():
    patches = {
        "12.0": ["requirements_patches/odoo12_compat.txt"],
        "19.0": ["requirements_patches/odoo19_fix.txt"],
    }
    result = resolve_patches(odoo_version="19.0", patches=patches)  # TODO: wire up
    assert result == ["requirements_patches/odoo19_fix.txt"]


@pytest.mark.config_schemas
@pytest.mark.requirements_patching
def test_resolve_patches_returns_empty_for_unmatched_version():
    patches = {
        "12.0": ["requirements_patches/odoo12_compat.txt"],
    }
    result = resolve_patches(odoo_version="17.0", patches=patches)  # TODO: wire up
    assert result == []


@pytest.mark.config_schemas
@pytest.mark.requirements_patching
def test_resolve_patches_returns_multiple_files():
    patches = {
        "19" : ["requirements_patches/fix1.txt", "requirements_patches/fix2.txt"],
    }
    result = resolve_patches(odoo_version="19", patches=patches)  # TODO: wire up
    assert result == ["requirements_patches/fix1.txt", "requirements_patches/fix2.txt"]


@pytest.mark.config_schemas
@pytest.mark.requirements_patching
def test_resolve_patches_major_version_key_matches():
    """workspace.toml uses "19" as key (major version string), not "19.0"."""
    patches = {
        "19": ["requirements_patches/odoo19_fix.txt"],
    }
    result = resolve_patches(odoo_version="19", patches=patches)  # TODO: wire up
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
