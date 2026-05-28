import os
import subprocess
from typing import Protocol, runtime_checkable


@runtime_checkable
class ProxyBackend(Protocol):
    def write_instance(
        self, name: str, http_port: int, gevent_port: int,
        domain_suffix: str, workspace_root: str,
    ) -> None: ...

    def remove_instance(self, name: str, workspace_root: str) -> None: ...


class NginxBackend:
    def write_instance(
        self, name: str, http_port: int, gevent_port: int,
        domain_suffix: str, workspace_root: str,
    ) -> None:
        upstream = name.replace("-", "_")
        block = (
            f"upstream {upstream} {{ server 127.0.0.1:{http_port}; }}\n"
            f"upstream {upstream}_lp {{ server 127.0.0.1:{gevent_port}; }}\n"
            f"server {{\n"
            f"    listen 443 ssl;\n"
            f"    server_name {name}.{domain_suffix};\n"
            f"\n"
            f"    proxy_read_timeout 720s;\n"
            f"    proxy_set_header X-Forwarded-Host $host;\n"
            f"    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            f"    proxy_set_header X-Forwarded-Proto $scheme;\n"
            f"    proxy_set_header X-Real-IP $remote_addr;\n"
            f"\n"
            f"    location / {{ proxy_pass http://{upstream}; }}\n"
            f"    location /longpolling {{ proxy_pass http://{upstream}_lp; }}\n"
            f"}}\n"
        )
        proxy_dir = os.path.join(workspace_root, "_proxy")
        os.makedirs(proxy_dir, exist_ok=True)
        with open(os.path.join(proxy_dir, f"{name}.conf"), "w") as f:
            f.write(block)

    def remove_instance(self, name: str, workspace_root: str) -> None:
        path = os.path.join(workspace_root, "_proxy", f"{name}.conf")
        if os.path.exists(path):
            os.remove(path)


class CaddyBackend:
    def __init__(self, caddy_config: str | None = None) -> None:
        raw = caddy_config or "~/.config/caddy/Caddyfile"
        self._caddy_config = os.path.expanduser(raw)

    def write_instance(
        self, name: str, http_port: int, gevent_port: int,
        domain_suffix: str, workspace_root: str,
    ) -> None:
        block = (
            f"{name}.{domain_suffix} {{\n"
            f"    reverse_proxy /longpolling/* localhost:{gevent_port}\n"
            f"    reverse_proxy localhost:{http_port}\n"
            f"    tls internal\n"
            f"}}\n"
        )
        proxy_dir = os.path.join(workspace_root, "_proxy")
        os.makedirs(proxy_dir, exist_ok=True)
        with open(os.path.join(proxy_dir, f"{name}.caddy"), "w") as f:
            f.write(block)
        self._reload()

    def remove_instance(self, name: str, workspace_root: str) -> None:
        path = os.path.join(workspace_root, "_proxy", f"{name}.caddy")
        if os.path.exists(path):
            os.remove(path)
        self._reload()

    def _reload(self) -> None:
        if os.path.exists(self._caddy_config):
            subprocess.run(
                ["caddy", "reload", "--config", self._caddy_config],
                check=False, capture_output=True,
            )


def get_proxy_backend(proxy_conf) -> ProxyBackend | None:
    if proxy_conf is None:
        return None
    backend = getattr(proxy_conf, "backend", "nginx")
    if backend == "caddy":
        return CaddyBackend(getattr(proxy_conf, "caddy_config", None))
    return NginxBackend()
