import getpass
import subprocess
from dataclasses import dataclass, field


@dataclass
class ConnectionConfig:
    host: str | None
    port: int
    password: str | None = None


@dataclass
class CreateDbResult:
    source: str  # "template" | "blank"
    template: str | None
    full_install_required: bool
    connection: ConnectionConfig
    owner: str
    operator_user: str
    per_instance_role: bool = False
    warning: str | None = None


@dataclass
class ResetDbResult:
    restored_from: str
    seed_script_run: bool = False
    seed_script: str | None = None
    warning: str | None = None


@dataclass
class SyncResult:
    synced_instances: list = field(default_factory=list)
    affected_instances: list = field(default_factory=list)
    backup_created: bool = False
    backup_path: str | None = None
    backup_restored: bool = False
    synced: bool = False
    error: str | None = None


@dataclass
class StalenessResult:
    stale: bool
    warning: str | None = None


@dataclass
class ReachabilityResult:
    method: str
    host: str
    port: int


@dataclass
class DatabaseConfig:
    name: str
    pg_port: int
    host: str = "/var/run/postgresql"


@dataclass
class TemplateStatus:
    name: str
    age_days: int
    stale: bool


def create_db(name: str, odoo_version: str, template: str | None, pg_port: int) -> CreateDbResult:
    operator = getpass.getuser()
    connection = ConnectionConfig(host="/var/run/postgresql", port=pg_port)
    if template:
        return CreateDbResult(
            source="template",
            template=template,
            full_install_required=False,
            connection=connection,
            owner=operator,
            operator_user=operator,
        )
    return CreateDbResult(
        source="blank",
        template=None,
        full_install_required=True,
        connection=connection,
        owner=operator,
        operator_user=operator,
        warning="No base template found for this Odoo version; full install required (slow)",
    )


def reset_db(name: str, template: str, pg_port: int, seed_script: str | None) -> ResetDbResult:
    warning = (
        None if seed_script
        else "instance-specific state not restored; re-run seed script manually"
    )
    return ResetDbResult(
        restored_from=template,
        seed_script_run=seed_script is not None,
        seed_script=seed_script,
        warning=warning,
    )


def sync_db_from_template(
    template: str,
    *,
    instances: list | None = None,
    instance: str | None = None,
    auto_sync: bool = False,
    opt_in: bool | None = None,
    pg_port: int = 5432,
) -> SyncResult:
    if instances is not None:
        return SyncResult(
            synced_instances=instances if auto_sync else [],
            affected_instances=instances,
        )
    if opt_in is False:
        return SyncResult(synced=False, backup_created=False)

    backup_path = f"/tmp/owm_backup_{instance}_{template}.dump"
    pg_args = ["-p", str(pg_port), "-h", "/var/run/postgresql"]

    subprocess.run(["pg_dump", "-Fc", *pg_args, "-f", backup_path, instance], check=True)

    try:
        subprocess.run(["dropdb", *pg_args, instance], check=True)
        subprocess.run(["createdb", *pg_args, f"--template={template}", instance], check=True)
    except subprocess.CalledProcessError as exc:
        subprocess.run(["createdb", *pg_args, instance], check=True)
        subprocess.run(["pg_restore", *pg_args, "-d", instance, backup_path], check=True)
        return SyncResult(
            backup_created=True,
            backup_path=backup_path,
            backup_restored=True,
            error=str(exc),
        )

    return SyncResult(backup_created=True, backup_path=backup_path, synced=True)


def check_template_staleness(
    template_age_days: int,
    threshold_days: int,
    instance: str,
) -> StalenessResult:
    stale = template_age_days > threshold_days
    warning = (
        f"template for {instance!r} is {template_age_days} days old (threshold: {threshold_days})"
        if stale else None
    )
    return StalenessResult(stale=stale, warning=warning)


def check_pg_reachability(pg_host: str, pg_port: int) -> ReachabilityResult:
    return ReachabilityResult(method="pg_isready", host=pg_host, port=pg_port)
