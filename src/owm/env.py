import json
import os


def resolve_env(
    instance: str,
    workspace_root: str,
    *,
    odoo_bin: str | None = None,
    instance_db_name: str | None = None,
    instance_pg_port: int | None = None,
    instance_http_port: int | None = None,
    instance_gevent_port: int | None = None,
) -> dict[str, str]:
    instance_dir = os.path.join(workspace_root, "instances", instance)
    venv_dir = os.path.join(instance_dir, ".venv")
    return {
        "ODOO_BIN":              odoo_bin if odoo_bin is not None else os.path.join(venv_dir, "bin", "odoo-bin"),
        "VENV_PYTHON":           os.path.join(venv_dir, "bin", "python"),
        "PSQL":                  "psql",
        "DB_NAME":               instance_db_name if instance_db_name is not None else "",
        "DB_PORT":               str(instance_pg_port) if instance_pg_port is not None else "",
        "INSTANCE_DIR":          instance_dir,
        "LOG_FILE":              os.path.join(instance_dir, "instance.log"),
        "HTTP_PORT":             str(instance_http_port) if instance_http_port is not None else "",
        "GEVENT_PORT":           str(instance_gevent_port) if instance_gevent_port is not None else "",
        "ODOO_CONF":             os.path.join(instance_dir, "instance.conf"),
        "WORKSPACE_DIR":         workspace_root,
        "SCRIPTS_DIR":           "",
        "WORKSPACE_SCRIPTS_DIR": "",
    }


def format_env(env: dict, fmt: str | None) -> str:
    if fmt == "dotenv":
        return "\n".join(f"{k}={v}" for k, v in env.items())
    if fmt == "json":
        return json.dumps(env, indent=2)
    if fmt == "shell":
        return "\n".join(f"export {k}={v}" for k, v in env.items())
    # human-readable default
    width = max(len(k) for k in env) if env else 0
    return "\n".join(f"{k:<{width}}  {v}" for k, v in env.items())
