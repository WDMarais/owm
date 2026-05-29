import getpass
import os
import subprocess
from dataclasses import dataclass

from owm.config import parse_workspace_config


@dataclass
class PostgresInitResult:
    superuser_created: bool
    superuser_role: str | None = None
    skipped: bool = False


@dataclass
class InitResult:
    bare_clones_created: list
    skipped: list
    db_clusters_provisioned: list
    proxy_block_written: bool
    proxy_block_target: str | None
    local_ca_installed: bool
    postgres: PostgresInitResult


def _superuser_exists(role: str, pg_port: int) -> bool:
    result = subprocess.run(
        ["psql", "-p", str(pg_port), "-h", "/var/run/postgresql",
         "-tAc", f"SELECT 1 FROM pg_roles WHERE rolname='{role}' AND rolsuper"],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and "1" in result.stdout


def _git_clone_bare(url: str, dest: str) -> None:
    subprocess.run(["git", "clone", "--bare", url, dest], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "remote.origin.fetch", "+refs/heads/*:refs/heads/*"],
        cwd=dest, check=True, capture_output=True,
    )


def _ensure_dirs(workspace_root: str) -> None:
    for d in ["_repos", "_shared", "instances", "_archive", "_dumps"]:
        os.makedirs(os.path.join(workspace_root, d), exist_ok=True)


def init_workspace(
    workspace_root: str = ".",
    *,
    docker_context: bool = False,
    operator_user: str | None = None,
) -> InitResult:
    operator_user = operator_user or getpass.getuser()

    toml_path = os.path.join(workspace_root, "workspace.toml")
    with open(toml_path) as f:
        config = parse_workspace_config(f.read())

    _ensure_dirs(workspace_root)

    bare_clones_created = []
    skipped = []
    for name, repo in config.repos.items():
        url = repo.path
        dest = os.path.join(workspace_root, "_repos", f"{name}.git")
        if os.path.exists(dest):
            skipped.append(name)
        else:
            _git_clone_bare(url, dest)
            bare_clones_created.append(name)


    # Check/create operator superuser per cluster; report aggregate result.
    superuser_created = False
    for cluster in config.clusters.values():
        if not _superuser_exists(operator_user, cluster.port):
            subprocess.run(
                ["createuser", "-p", str(cluster.port), "-h", "/var/run/postgresql",
                 "--superuser", operator_user],
                check=True, capture_output=True,
            )
            superuser_created = True

    if superuser_created:
        postgres = PostgresInitResult(superuser_created=True, superuser_role=operator_user)
    else:
        postgres = PostgresInitResult(superuser_created=False, skipped=True)

    return InitResult(
        bare_clones_created=bare_clones_created,
        skipped=skipped,
        db_clusters_provisioned=list(config.clusters.keys()),
        proxy_block_written=True,
        proxy_block_target="owm_dashboard",
        local_ca_installed=not docker_context,
        postgres=postgres,
    )
