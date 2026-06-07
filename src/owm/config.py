import os
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, computed_field, model_validator

from owm.errors import ConfigError, NOT_FOUND, OwmError


class ConfOwnership(StrEnum):
    """Ownership marker carried on the first lines of a generated instance.conf.

    MANAGED lets owm regenerate the file wholesale; MANUAL opts out so owm
    leaves it alone. An absent marker is not a state owm proceeds from: to drive
    a conf through owm you must explicitly declare it MANAGED or MANUAL, so the
    regen paths raise ODOO_CONFIG_UNMARKED rather than silently clobbering a
    hand-written conf whose ownership was never declared.
    """
    MANAGED = "# owm: managed"
    MANUAL  = "# owm: manual"

    @classmethod
    def detect(cls, conf_path: str) -> "ConfOwnership | None":
        """Return the ownership marker present in the conf at conf_path, or
        None if it carries no recognised marker."""
        with open(conf_path) as f:
            for line in f:
                for member in cls:
                    if line.startswith(member):
                        return member
        return None


def instance_config_path(instance: str, workspace_root: str) -> str:
    """Path to an instance's instance.toml, raising NOT_FOUND if it is absent.

    Centralizes the missing-instance guard so the lifecycle, operations, and
    sync orchestrators raise a shapeable OwmError(NOT_FOUND) instead of leaking
    a bare FileNotFoundError that adapters (CLI, MCP, dashboard) cannot shape.
    """
    path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    if not os.path.exists(path):
        raise OwmError(f"instance {instance!r} not found", code=NOT_FOUND)
    return path


def resolve_workspace_root(override: str | None = None) -> str:
    """Resolve the workspace root by the precedence owm and git both use:
    explicit override > OWM_WORKSPACE env var > walk up from cwd for workspace.toml.

    A deliberate signal (the --workspace flag, the exported OWM_WORKSPACE spine)
    beats the incidental cwd — mirroring git's `--git-dir > GIT_DIR > discovery` —
    so a workspace manager configured once works from anywhere. The override and
    env values are trusted as given (abspath'd, not validated); only the cwd-walkup
    fallback requires an actual workspace.toml on disk.

    Raises OwmError(NOT_FOUND) when none of the three resolve, so adapters surface
    one clear "no workspace" error instead of silently operating on '.'.
    """
    if override:
        return os.path.abspath(override)
    env = os.environ.get("OWM_WORKSPACE")
    if env:
        return os.path.abspath(env)
    # cwd.parents is the finite ancestor chain up to the filesystem root; walking
    # that bounded list (cwd first, then each parent) avoids an unbounded loop.
    cwd = Path.cwd()
    for ancestor in (cwd, *cwd.parents):
        if (ancestor / "workspace.toml").is_file():
            return str(ancestor)
    raise OwmError(
        "No workspace.toml found. Run from inside a workspace, set "
        "OWM_WORKSPACE, or pass --workspace.",
        code=NOT_FOUND,
    )


def cwd_workspace_conflict(resolved_root: str) -> str | None:
    """If the cwd sits inside a workspace different from resolved_root, return that
    other workspace's root; else None.

    resolve_workspace_root deliberately lets an override / OWM_WORKSPACE win over
    the cwd, but that means standing inside workspace B while operating on A is
    silent. This detector lets an adapter warn about the shadowing without changing
    which root wins. Returns None when the cwd is inside resolved_root itself (the
    walkup case) or inside no workspace at all.
    """
    target = os.path.abspath(resolved_root)
    cwd = Path.cwd()
    for ancestor in (cwd, *cwd.parents):
        if (ancestor / "workspace.toml").is_file():
            other = os.path.abspath(str(ancestor))
            return other if other != target else None
    return None


def _parse_repo_spec_string(spec: str) -> dict:
    """DSL string → field dict for RepoSpec.

    "feat-789-dev:main+readonly+exists"  →  branch/base/flags dict
    "12.0"                               →  bare branch, no base
    """
    if ":" in spec:
        branch, _, rest = spec.partition(":")
        parts = rest.split("+")
        base_or_flag = parts[0]
        flags = set(parts[1:])
        if base_or_flag == "shared":
            shared, base = True, None
        else:
            shared, base = False, base_or_flag
    else:
        parts = spec.split("+")
        branch = parts[0]
        flags = set(parts[1:])
        shared, base = False, None
    return {
        "branch": branch,
        "base": base,
        "shared": shared,
        "readonly": "readonly" in flags,
        "assert_exists": "exists" in flags,
        "create": "create" in flags,
    }


class RepoSpec(BaseModel):
    branch: str
    base: str | None = None
    shared: bool = False
    readonly: bool = False
    assert_exists: bool = False
    create: bool = False

    @model_validator(mode='before')
    @classmethod
    def _coerce(cls, data):
        if isinstance(data, str):
            return _parse_repo_spec_string(data)
        if isinstance(data, dict) and "exists" in data:
            # TOML inline-table uses "exists"; model field is assert_exists.
            data = dict(data)
            data["assert_exists"] = data.pop("exists")
        return data


class WorkspaceRepo(BaseModel):
    path: str
    has_addons: bool = False
    addons_paths: list[str] = ["."]

    @model_validator(mode='before')
    @classmethod
    def _from_string(cls, data):
        if isinstance(data, str):
            return {"path": data}
        return data


class ClusterConfig(BaseModel):
    pg_version: str
    port: int


class WorkspaceDefaults(BaseModel):
    instances_dir: str = "instances"
    http_port_range: list[int] = [8100, 8299]
    owm_port_range: list[int] = [8090, 8099]
    workers: int = 2
    sync_warn_hours: int = 72
    eviction_threshold: int = 10
    template_warn_days: int = 30
    repo_priority: list[str] | None = None


class ProxyConfig(BaseModel):
    domain_suffix: str
    backend: str = "nginx"
    caddy_config: str | None = None


class WorkspaceScripts(BaseModel):
    scripts_dir: str


@dataclass
class WorkspaceConfig:
    repos: dict[str, WorkspaceRepo]
    clusters: dict[str, ClusterConfig]
    defaults: WorkspaceDefaults
    patches: dict[str, list[str]]
    compare_pairs: list[list[str]]
    proxy: ProxyConfig | None
    scripts: WorkspaceScripts | None


class DatabaseSection(BaseModel):
    name: str
    pg_port: int
    template: str | None = None


class ServerSection(BaseModel):
    # extra='ignore' so an explicit gevent_port in the TOML (validated then
    # discarded) doesn't land as an unknown-field error.
    model_config = ConfigDict(extra='ignore')

    http_port: int = 0
    workers: int = 2
    odoo_repo: str | None = None  # explicit Odoo source repo; falls back to the shared repo

    @model_validator(mode='before')
    @classmethod
    def _check_gevent(cls, data):
        if isinstance(data, dict):
            http_port = data.get("http_port", 0)
            explicit_gevent = data.get("gevent_port")
            if explicit_gevent is not None and http_port and explicit_gevent != http_port + 1:
                raise ValueError(
                    f"gevent_port is derived as http_port + 1 ({http_port + 1}); "
                    f"remove it from the toml or set it to {http_port + 1} (got {explicit_gevent})"
                )
        return data

    @computed_field
    @property
    def gevent_port(self) -> int:
        # Derived, not stored: the gevent/longpolling port is conventionally http_port + 1.
        # Keeping it a computed_field (rather than a stored field) makes the only invalid
        # state — gevent != http+1 — unrepresentable, so there's nothing to drift or validate.
        return self.http_port + 1 if self.http_port else 0


class InstallSection(BaseModel):
    modules: list[str] = []


class PythonSection(BaseModel):
    version: str | None = None


class ScriptRunner(BaseModel):
    file: str
    type: str


class ScriptCompare(BaseModel):
    target: str


class InstanceScripts(BaseModel):
    default: str | None = None
    scripts_dir: str | None = None
    runners: dict[str, ScriptRunner] = {}
    compare: ScriptCompare | None = None


class TemplateSection(BaseModel):
    sync_opt_in: bool = False


@dataclass
class InstanceConfig:
    repos: dict[str, RepoSpec]
    database: DatabaseSection
    server: ServerSection
    install: InstallSection | None = None
    python: PythonSection | None = None
    scripts: InstanceScripts | None = None
    template: TemplateSection | None = None


def parse_repo_spec(spec: str | dict) -> RepoSpec:
    """Parse a repo spec from either string DSL or TOML inline-table form.

    String DSL:   "feat-789-dev:main+readonly+exists"
    Bare branch:  "12.0"  (no colon → no base, matching owm's tolerant form)
    Inline table: {branch = "feat-789-dev", base = "main", readonly = true, exists = true}
    """
    return RepoSpec.model_validate(spec)


def parse_workspace_config(toml: str) -> WorkspaceConfig:
    try:
        raw = tomllib.loads(toml)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid workspace.toml: {e}") from e

    if "repos" not in raw:
        raise ConfigError("workspace.toml must have [repos]")
    if "clusters" not in raw:
        raise ConfigError("workspace.toml must have [clusters]")

    repos_raw = dict(raw["repos"])

    repos: dict[str, WorkspaceRepo] = {}
    for name, val in repos_raw.items():
        if isinstance(val, str):
            repos[name] = WorkspaceRepo(path=val)
        else:
            repos[name] = WorkspaceRepo(
                path=val["path"],
                has_addons=val.get("has_addons", False),
                addons_paths=val.get("addons_paths", ["."]),
            )

    clusters = {
        k: ClusterConfig(pg_version=v["pg_version"], port=v["port"])
        for k, v in raw["clusters"].items()
    }

    dr = raw.get("defaults", {})
    if "http_port_range" in dr and not isinstance(dr["http_port_range"], list):
        raise ConfigError("workspace.toml: http_port_range must be a list")
    defaults = WorkspaceDefaults(
        instances_dir=dr.get("instances_dir", "instances"),
        http_port_range=dr.get("http_port_range", [8100, 8299]),
        owm_port_range=dr.get("owm_port_range", [8090, 8099]),
        workers=dr.get("workers", 2),
        sync_warn_hours=dr.get("sync_warn_hours", 72),
        eviction_threshold=dr.get("eviction_threshold", 10),
        template_warn_days=dr.get("template_warn_days", 30),
        repo_priority=dr.get("repo_priority", None),
    )

    patches = raw.get("patches", {})
    compare_pairs = raw.get("compare_pairs", {}).get("pairs", [])

    proxy = None
    if "proxy" in raw:
        p = raw["proxy"]
        proxy = ProxyConfig(
            domain_suffix=p["domain_suffix"],
            backend=p.get("backend", "nginx"),
            caddy_config=p.get("caddy_config"),
        )

    scripts = None
    if "scripts" in raw:
        scripts = WorkspaceScripts(scripts_dir=raw["scripts"]["scripts_dir"])

    return WorkspaceConfig(
        repos=repos,
        clusters=clusters,
        defaults=defaults,
        patches=patches,
        compare_pairs=compare_pairs,
        proxy=proxy,
        scripts=scripts,
    )


def parse_instance_config(toml: str) -> InstanceConfig:
    try:
        raw = tomllib.loads(toml)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid instance.toml: {e}") from e

    if "database" not in raw:
        raise ConfigError("instance.toml must have [database]")
    if "server" not in raw:
        raise ConfigError("instance.toml must have [server]")

    repos = {}
    for name, spec in raw.get("repos", {}).items():
        try:
            repos[name] = parse_repo_spec(spec)
        except (ValueError, TypeError) as e:
            raise ConfigError(
                f"instance.toml: invalid repo spec for {name!r} ({spec!r}): {e}"
            ) from e

    db = raw["database"]
    try:
        database = DatabaseSection(
            name=db["name"],
            pg_port=db["pg_port"],
            template=db.get("template"),
        )
    except (KeyError, TypeError) as e:
        raise ConfigError(f"instance.toml: [database] missing required key {e}") from e

    srv = raw["server"]
    http_port = srv.get("http_port", 0)
    # gevent_port is derived (http_port + 1), not stored — see ServerSection.gevent_port.
    # An explicit gevent_port in the toml is only honoured if it matches; a mismatch is a
    # hand-edit mistake and is rejected loudly rather than silently ignored.
    explicit_gevent = srv.get("gevent_port")
    if explicit_gevent is not None and http_port and explicit_gevent != http_port + 1:
        raise ConfigError(
            f"gevent_port is derived as http_port + 1 ({http_port + 1}); "
            f"remove it from the toml or set it to {http_port + 1} (got {explicit_gevent})"
        )
    server = ServerSection(
        http_port=http_port,
        workers=srv.get("workers", 2),
        odoo_repo=srv.get("odoo_repo"),
    )

    install = None
    if "install" in raw:
        install = InstallSection(modules=raw["install"].get("modules", []))

    python = None
    if "python" in raw:
        python = PythonSection(version=raw["python"].get("version"))

    scripts = None
    if "scripts" in raw:
        s = raw["scripts"]
        runners = {}
        for rname, r in s.get("runners", {}).items():
            try:
                runners[rname] = ScriptRunner(file=r["file"], type=r["type"])
            except (KeyError, TypeError) as e:
                raise ConfigError(
                    f"instance.toml: [scripts.runners].{rname} must be a table with "
                    f"'file' and 'type' keys (got {r!r})"
                ) from e
        try:
            compare = ScriptCompare(target=s["compare"]["target"]) if "compare" in s else None
        except (KeyError, TypeError) as e:
            raise ConfigError(f"instance.toml: invalid [scripts.compare]: {e}") from e
        scripts = InstanceScripts(
            default=s.get("default"),
            scripts_dir=s.get("scripts_dir"),
            runners=runners,
            compare=compare,
        )

    template = None
    if "template" in raw:
        template = TemplateSection(sync_opt_in=raw["template"].get("sync_opt_in", False))

    return InstanceConfig(
        repos=repos,
        database=database,
        server=server,
        install=install,
        python=python,
        scripts=scripts,
        template=template,
    )


def load_instance_config(instance: str, workspace_root: str) -> InstanceConfig:
    """Read and parse an instance's instance.toml, by name, in one step.

    The single by-name loader: pairs the missing-instance guard
    (`instance_config_path` -> OwmError NOT_FOUND) with the open+read+parse
    (`parse_instance_config` -> ConfigError on malformed toml) that the
    lifecycle, operations and sync paths otherwise repeat inline. Adapters
    shape the two failure modes by catching OwmError (NOT_FOUND) and
    ConfigError (OWM_CONFIG_INVALID).

    Directory-enumeration callers that already hold a path from a workspace
    scan keep calling `parse_instance_config` directly — they reach the toml
    by listing, not by name, so the path guard would only re-derive what they
    already have.
    """
    with open(instance_config_path(instance, workspace_root)) as f:
        return parse_instance_config(f.read())
