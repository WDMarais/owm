import getpass
import subprocess
from dataclasses import dataclass, field

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


def init_workspace(
    workspace_root: str | None = None,
    workspace_toml_content: str | None = None,
    *,
    docker_context: bool = False,
    existing_repos: list[str] | None = None,
    pg_port: int = 5432,
    operator_user: str | None = None,
) -> InitResult:
    operator_user = operator_user or getpass.getuser()
    existing = set(existing_repos or [])

    repos: dict = {}
    clusters: dict = {}
    if workspace_toml_content:
        config = parse_workspace_config(workspace_toml_content)
        repos = config.repos
        clusters = config.clusters

    bare_clones_created = [r for r in repos if r not in existing]
    skipped = [r for r in repos if r in existing]
    db_clusters_provisioned = list(clusters.keys())

    if _superuser_exists(operator_user, pg_port):
        postgres = PostgresInitResult(superuser_created=False, skipped=True)
    else:
        subprocess.run(
            ["createuser", "-p", str(pg_port), "-h", "/var/run/postgresql",
             "--superuser", operator_user],
            check=True,
        )
        postgres = PostgresInitResult(superuser_created=True, superuser_role=operator_user)

    return InitResult(
        bare_clones_created=bare_clones_created,
        skipped=skipped,
        db_clusters_provisioned=db_clusters_provisioned,
        proxy_block_written=True,
        proxy_block_target="owm_dashboard",
        local_ca_installed=not docker_context,
        postgres=postgres,
    )
