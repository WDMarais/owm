import tomllib
from dataclasses import dataclass, field


@dataclass
class RepoSpec:
    branch: str
    base: str | None
    shared: bool
    readonly: bool
    exists: bool


@dataclass
class RepoMeta:
    has_addons: bool
    addons_paths: list[str] = field(default_factory=lambda: ["."])


@dataclass
class ClusterConfig:
    pg_version: str
    port: int


@dataclass
class WorkspaceDefaults:
    instances_dir: str = "instances"
    http_port_range: list[int] = field(default_factory=lambda: [8100, 8299])
    owm_port_range: list[int] = field(default_factory=lambda: [8090, 8099])
    workers: int = 2
    sync_warn_hours: int = 72
    eviction_threshold: int = 10
    template_warn_days: int = 30
    repo_priority: list[str] | None = None


@dataclass
class ProxyConfig:
    domain_suffix: str


@dataclass
class WorkspaceScripts:
    scripts_dir: str


@dataclass
class WorkspaceConfig:
    repos: dict[str, str]
    repos_meta: dict[str, RepoMeta]
    clusters: dict[str, ClusterConfig]
    defaults: WorkspaceDefaults
    patches: dict[str, list[str]]
    compare_pairs: list[list[str]]
    proxy: ProxyConfig | None
    scripts: WorkspaceScripts | None


@dataclass
class DatabaseSection:
    name: str
    pg_port: int
    template: str | None = None


@dataclass
class ServerSection:
    http_port: int
    gevent_port: int
    workers: int = 2


@dataclass
class InstallSection:
    modules: list[str]


@dataclass
class PythonSection:
    version: str | None


@dataclass
class ScriptRunner:
    file: str
    type: str


@dataclass
class ScriptCompare:
    target: str


@dataclass
class InstanceScripts:
    default: str | None = None
    scripts_dir: str | None = None
    runners: dict[str, ScriptRunner] = field(default_factory=dict)
    compare: ScriptCompare | None = None


@dataclass
class TemplateSection:
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


def parse_repo_spec(spec: str) -> RepoSpec:
    colon = spec.index(":")
    branch = spec[:colon]
    parts = spec[colon + 1:].split("+")
    base_or_flag = parts[0]
    flags = set(parts[1:])

    if base_or_flag == "shared":
        shared, base = True, None
    else:
        shared, base = False, base_or_flag

    return RepoSpec(
        branch=branch,
        base=base,
        shared=shared,
        readonly="readonly" in flags,
        exists="exists" in flags,
    )


def parse_workspace_config(toml: str) -> WorkspaceConfig:
    try:
        raw = tomllib.loads(toml)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"invalid TOML: {e}") from e

    if "repos" not in raw:
        raise ValueError("workspace.toml must have [repos]")
    if "clusters" not in raw:
        raise ValueError("workspace.toml must have [clusters]")

    repos_raw = dict(raw["repos"])
    if "meta" in repos_raw and isinstance(repos_raw["meta"], str):
        raise ValueError(
            "'meta' is a reserved key in [repos] and cannot be used as a repo name; "
            "rename the repo and use [repos.meta] for per-repo metadata"
        )
    meta_raw = repos_raw.pop("meta", {})

    repos_meta: dict[str, RepoMeta] = {}
    for name, meta in meta_raw.items():
        repos_meta[name] = RepoMeta(
            has_addons=meta.get("has_addons", False),
            addons_paths=meta.get("addons_paths", ["."]),
        )
    for name in repos_raw:
        if name not in repos_meta:
            repos_meta[name] = RepoMeta(has_addons=False)

    clusters = {
        k: ClusterConfig(pg_version=v["pg_version"], port=v["port"])
        for k, v in raw["clusters"].items()
    }

    dr = raw.get("defaults", {})
    if "http_port_range" in dr and not isinstance(dr["http_port_range"], list):
        raise ValueError("http_port_range must be a list")
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
        proxy = ProxyConfig(domain_suffix=raw["proxy"]["domain_suffix"])

    scripts = None
    if "scripts" in raw:
        scripts = WorkspaceScripts(scripts_dir=raw["scripts"]["scripts_dir"])

    return WorkspaceConfig(
        repos=repos_raw,
        repos_meta=repos_meta,
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
        raise ValueError(f"invalid TOML: {e}") from e

    if "database" not in raw:
        raise ValueError("instance.toml must have [database]")
    if "server" not in raw:
        raise ValueError("instance.toml must have [server]")

    repos = {name: parse_repo_spec(spec) for name, spec in raw.get("repos", {}).items()}

    db = raw["database"]
    database = DatabaseSection(
        name=db["name"],
        pg_port=db["pg_port"],
        template=db.get("template"),
    )

    srv = raw["server"]
    http_port, gevent_port = srv["http_port"], srv["gevent_port"]
    if gevent_port != http_port + 1:
        raise ValueError(
            f"gevent_port must equal http_port + 1 (got http={http_port}, gevent={gevent_port})"
        )
    server = ServerSection(
        http_port=http_port,
        gevent_port=gevent_port,
        workers=srv.get("workers", 2),
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
        runners = {
            name: ScriptRunner(file=r["file"], type=r["type"])
            for name, r in s.get("runners", {}).items()
        }
        compare = ScriptCompare(target=s["compare"]["target"]) if "compare" in s else None
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
