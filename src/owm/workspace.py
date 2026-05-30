import getpass
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from owm.config import parse_workspace_config


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CloneResult:
    name: str
    status: str  # "cloned" | "local_copy" | "skipped" | "error"
    error: str | None = None


@dataclass
class PostgresInitResult:
    superuser_created: bool
    superuser_role: str | None = None
    skipped: bool = False
    clusters_created: list = field(default_factory=list)
    clusters_started: list = field(default_factory=list)


@dataclass
class InitResult:
    bare_clones_created: list      # repo names newly cloned
    skipped: list                  # repo names already existed
    clones: list                   # list[CloneResult] with full per-repo detail
    db_clusters_provisioned: list  # cluster keys from [clusters]
    proxy_block_written: bool      # True if proxy dir created (always True)
    proxy_stub_path: str | None    # path to written proxy stub file, if any
    local_ca_installed: bool       # False in docker_context mode
    postgres: PostgresInitResult


# ---------------------------------------------------------------------------
# Postgres helpers
# ---------------------------------------------------------------------------

def _pg_is_ready(port: int) -> bool:
    result = subprocess.run(
        ["pg_isready", "-p", str(port), "-h", "/var/run/postgresql"],
        capture_output=True,
    )
    return result.returncode == 0


def _cluster_exists(pg_version: str, cluster_name: str) -> bool:
    result = subprocess.run(["pg_lsclusters", "-h"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == pg_version and parts[1] == cluster_name:
            return True
    return False


def _cluster_running(pg_version: str, cluster_name: str) -> bool:
    result = subprocess.run(["pg_lsclusters", "-h"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == pg_version and parts[1] == cluster_name:
            return parts[3] == "online"
    return False


def _create_cluster(pg_version: str, cluster_name: str, port: int) -> None:
    subprocess.run(
        ["sudo", "pg_createcluster", "--port", str(port), pg_version, cluster_name],
        check=True,
    )


def _start_cluster(pg_version: str, cluster_name: str) -> None:
    subprocess.run(
        ["sudo", "pg_ctlcluster", pg_version, cluster_name, "start"],
        check=True,
    )


def _superuser_exists(role: str, pg_port: int) -> bool:
    result = subprocess.run(
        ["psql", "-p", str(pg_port), "-h", "/var/run/postgresql", "-d", "postgres",
         "-tAc", f"SELECT 1 FROM pg_roles WHERE rolname='{role}' AND rolsuper"],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and "1" in result.stdout


def _create_superuser_role(role: str, pg_port: int) -> None:
    subprocess.run(
        ["createuser", "-p", str(pg_port), "-h", "/var/run/postgresql",
         "--superuser", role],
        check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------

def _ensure_dirs(workspace_root: str) -> None:
    for d in ["_repos", "_shared", "instances", "_archive", "_dumps", "_proxy"]:
        os.makedirs(os.path.join(workspace_root, d), exist_ok=True)
    log_path = os.path.join(workspace_root, "owm.log")
    if not os.path.exists(log_path):
        open(log_path, "a").close()


# ---------------------------------------------------------------------------
# Git clone helpers
# ---------------------------------------------------------------------------

def _git_clone_bare(url: str, dest: str) -> None:
    subprocess.run(["git", "clone", "--bare", url, dest], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "remote.origin.fetch", "+refs/heads/*:refs/heads/*"],
        cwd=dest, check=True, capture_output=True,
    )


def _git_clone_from_local(local_path: str, upstream_url: str, dest: str) -> None:
    """Clone from an on-disk copy, then fix the remote to the real upstream URL."""
    subprocess.run(["git", "clone", "--bare", local_path, dest], check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "set-url", "origin", upstream_url],
        cwd=dest, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "remote.origin.fetch", "+refs/heads/*:refs/heads/*"],
        cwd=dest, check=True, capture_output=True,
    )


def _clone_repo(name: str, url: str, dest: str, local_copy: str | None) -> CloneResult:
    if os.path.exists(dest):
        return CloneResult(name=name, status="skipped")
    try:
        if local_copy and os.path.isdir(local_copy):
            _git_clone_from_local(local_copy, url, dest)
            return CloneResult(name=name, status="local_copy")
        _git_clone_bare(url, dest)
        return CloneResult(name=name, status="cloned")
    except subprocess.CalledProcessError as e:
        return CloneResult(name=name, status="error", error=str(e))


# ---------------------------------------------------------------------------
# Proxy stub
# ---------------------------------------------------------------------------

def _write_proxy_stub(workspace_root: str, proxy) -> str | None:
    if proxy is None:
        return None
    abs_proxy_dir = os.path.abspath(os.path.join(workspace_root, "_proxy"))
    if proxy.backend == "caddy":
        stub_path = os.path.join(abs_proxy_dir, "00-owm-include.caddy")
        content = (
            "# owm workspace — Caddy include setup\n"
            "# Add the following line to your Caddyfile:\n"
            f"#   import {abs_proxy_dir}/*.caddy\n"
            "# Then reload: caddy reload\n"
        )
        with open(stub_path, "w") as f:
            f.write(content)
        return stub_path
    if proxy.backend == "nginx":
        stub_path = os.path.join(abs_proxy_dir, "owm-include.conf")
        content = (
            "# owm workspace — nginx include block\n"
            "# Symlink and enable:\n"
            f"#   sudo ln -s {stub_path} /etc/nginx/sites-available/owm\n"
            "#   sudo ln -s /etc/nginx/sites-available/owm /etc/nginx/sites-enabled/owm\n"
            "#   sudo nginx -t && sudo systemctl reload nginx\n"
            f"include {abs_proxy_dir}/*.nginx.conf;\n"
        )
        with open(stub_path, "w") as f:
            f.write(content)
        return stub_path
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def init_workspace(
    workspace_root: str = ".",
    *,
    docker_context: bool = False,
    local_copies_dir: str | None = None,
    operator_user: str | None = None,
) -> InitResult:
    """Initialise a workspace from workspace.toml.

    - Creates directory structure (_repos/, _shared/, instances/, _archive/, _dumps/, _proxy/).
    - Bare-clones all repos declared in [repos]; idempotent (skips existing).
    - Provisions Postgres clusters from [clusters]: creates if absent, starts if stopped,
      ensures operator superuser role exists. Uses pg_isready to skip if already running.
    - Writes a proxy config stub (_proxy/) appropriate to proxy.backend (caddy or nginx).

    Pass local_copies_dir to clone from an existing on-disk workspace instead of downloading
    (e.g. owm init --local-copies ~/old-workspace). Objects are fully copied; no shared
    object store. After init, set the real upstream with the usual remote or just run
    owm fetch to verify.
    """
    operator_user = operator_user or getpass.getuser()
    workspace_root = os.path.abspath(workspace_root)

    toml_path = os.path.join(workspace_root, "workspace.toml")
    with open(toml_path) as f:
        config = parse_workspace_config(f.read())

    _ensure_dirs(workspace_root)

    # Build per-repo local copy paths if --local-copies given
    local_copies: dict[str, str] = {}
    if local_copies_dir:
        repos_subdir = os.path.join(local_copies_dir, "_repos")
        if os.path.isdir(repos_subdir):
            for name in config.repos:
                candidate = os.path.join(repos_subdir, f"{name}.git")
                if os.path.isdir(candidate):
                    local_copies[name] = candidate

    # Clone repos in parallel
    clone_tasks = [
        (
            name,
            repo.path,
            os.path.join(workspace_root, "_repos", f"{name}.git"),
            local_copies.get(name),
        )
        for name, repo in config.repos.items()
    ]
    clones: list[CloneResult] = []
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_clone_repo, name, url, dest, local): name
            for name, url, dest, local in clone_tasks
        }
        for future in as_completed(futures):
            clones.append(future.result())

    bare_clones_created = [c.name for c in clones if c.status in ("cloned", "local_copy")]
    skipped = [c.name for c in clones if c.status == "skipped"]

    # Postgres cluster setup — idempotent
    clusters_created: list[str] = []
    clusters_started: list[str] = []
    superuser_created = False
    for key, cluster in config.clusters.items():
        cluster_name = f"owm-{key}"
        if not _pg_is_ready(cluster.port):
            if not _cluster_exists(cluster.pg_version, cluster_name):
                _create_cluster(cluster.pg_version, cluster_name, cluster.port)
                clusters_created.append(cluster_name)
            if not _cluster_running(cluster.pg_version, cluster_name):
                _start_cluster(cluster.pg_version, cluster_name)
                clusters_started.append(cluster_name)
        if not _superuser_exists(operator_user, cluster.port):
            _create_superuser_role(operator_user, cluster.port)
            superuser_created = True

    postgres = PostgresInitResult(
        superuser_created=superuser_created,
        superuser_role=operator_user if superuser_created else None,
        skipped=not (clusters_created or clusters_started or superuser_created),
        clusters_created=clusters_created,
        clusters_started=clusters_started,
    )

    proxy_stub_path = _write_proxy_stub(workspace_root, config.proxy)

    return InitResult(
        bare_clones_created=bare_clones_created,
        skipped=skipped,
        clones=clones,
        db_clusters_provisioned=list(config.clusters.keys()),
        proxy_block_written=True,
        proxy_stub_path=proxy_stub_path,
        local_ca_installed=not docker_context,
        postgres=postgres,
    )
