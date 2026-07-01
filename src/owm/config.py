import os
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field, model_validator

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


def instances_root(workspace_root: str) -> str:
    """The workspace's instances directory (part of the skeleton; always present)."""
    return os.path.join(workspace_root, "instances")


def instance_config_path(instance: str, workspace_root: str) -> str:
    """Path to an instance's instance.toml, raising NOT_FOUND if it is absent.

    Centralizes the missing-instance guard so the lifecycle, operations, and
    sync orchestrators raise a shapeable OwmError(NOT_FOUND) instead of leaking
    a bare FileNotFoundError that adapters (CLI, MCP, dashboard) cannot shape.
    """
    path = os.path.join(instances_root(workspace_root), instance, "instance.toml")
    if not os.path.exists(path):
        raise OwmError(f"instance {instance!r} not found", code=NOT_FOUND)
    return path


def list_instances(workspace_root: str) -> list[str]:
    """Names of configured instances — dirs under instances_root with an instance.toml."""
    return sorted(
        e.name for e in os.scandir(instances_root(workspace_root))
        if e.is_dir() and not e.name.startswith(("_", "."))
        and os.path.exists(os.path.join(e.path, "instance.toml"))
    )


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

    @model_validator(mode='after')
    def _reject_plus_in_refs(self):
        # A '+' surviving into a branch/base name means a flag landed in the wrong
        # place: '+create' before the colon ("branch+create:base"), or stuffed into
        # the branch value of a table. The string DSL only reads flags after the
        # base, so the rest silently becomes part of the name — caught here instead.
        for field in ("branch", "base"):
            val = getattr(self, field)
            if val and "+" in val:
                raise ValueError(
                    f"{field} {val!r} contains '+', which looks like a misplaced flag. "
                    "In the string form flags go after the base (e.g. 'branch:base+create'); "
                    'or use the table form (e.g. {branch = "...", base = "...", create = true}).'
                )
        return self


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


class WorkspaceConfig(BaseModel):
    repos: dict[str, WorkspaceRepo]
    clusters: dict[str, ClusterConfig]
    defaults: WorkspaceDefaults = Field(default_factory=WorkspaceDefaults)
    patches: dict[str, list[str]] = {}
    compare_pairs: list[list[str]] = []
    proxy: ProxyConfig | None = None
    scripts: WorkspaceScripts | None = None

    @model_validator(mode='before')
    @classmethod
    def _normalise(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            # TOML: [compare_pairs] / pairs = [...] — unnest to a flat list.
            cp = data.get("compare_pairs", {})
            if isinstance(cp, dict):
                data["compare_pairs"] = cp.get("pairs", [])
        return data


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
    # Explicit Odoo major version. Overrides branch-name inference — the escape
    # hatch for branches that don't encode a parseable version (or where the
    # inference would guess wrong). Drives the conf port directive and the
    # requirements-suffix lookup.
    odoo_version: int | None = None

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
    # Explicit requirements files (relative to the instance dir, or absolute).
    # When set, they override the per-repo inference in _collect_requirements —
    # the escape hatch for repos whose file naming doesn't match the convention.
    requirements: list[str] | None = None


class ScriptRunner(BaseModel):
    file: str
    type: Literal["odoo-shell", "python"]  # odoo-shell = python piped through odoo-bin shell (ORM env bound); python = bare python, no ORM


class ScriptCompare(BaseModel):
    target: str


class InstanceScripts(BaseModel):
    default: str | None = None
    scripts_dir: str | None = None
    runners: dict[str, ScriptRunner] = {}
    compare: ScriptCompare | None = None


class TemplateSection(BaseModel):
    sync_opt_in: bool = False


class InstanceConfig(BaseModel):
    repos: dict[str, RepoSpec] = {}
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


def _config_error_from_validation(label: str, e: ValidationError) -> ConfigError:
    """Build a one-line ConfigError from a pydantic ValidationError.

    pydantic's default str() is a multi-line dump; embedding it leaks an ugly
    blob into every consumer (CLI line, dashboard notification). Summarise to
    the first offending field plus an overflow count, and keep the full
    structured list in .extra for consumers that want to expand it."""
    details = [
        {"loc": ".".join(str(p) for p in err["loc"]), "msg": err["msg"]}
        for err in e.errors()
    ]
    first = details[0]
    summary = f"{first['loc']}: {first['msg']}"
    if len(details) > 1:
        summary += f" (+{len(details) - 1} more)"
    return ConfigError(f"invalid {label}: {summary}", errors=details)


def parse_workspace_config(toml: str) -> WorkspaceConfig:
    try:
        raw = tomllib.loads(toml)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid workspace.toml: {e}") from e
    try:
        return WorkspaceConfig.model_validate(raw)
    except ValidationError as e:
        raise _config_error_from_validation("workspace.toml", e) from e


def parse_instance_config(toml: str) -> InstanceConfig:
    try:
        raw = tomllib.loads(toml)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid instance.toml: {e}") from e
    try:
        return InstanceConfig.model_validate(raw)
    except ValidationError as e:
        raise _config_error_from_validation("instance.toml", e) from e


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
