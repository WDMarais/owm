import os
import subprocess
import sys
from typing import Protocol, runtime_checkable


@runtime_checkable
class ProxyBackend(Protocol):
    # The scheme this backend serves instances over — nginx terminates plain
    # http (listen 80), Caddy serves https (tls internal). web.base.url must
    # match, or Odoo advertises a scheme the proxy doesn't answer on.
    scheme: str

    def write_instance(
        self, name: str, http_port: int, gevent_port: int,
        domain_suffix: str, workspace_root: str,
    ) -> None: ...

    def remove_instance(self, name: str, workspace_root: str) -> None: ...


def _nginx_reload() -> bool:
    """Best-effort `sudo nginx -s reload` so a written/removed block takes effect.
    Never raises: a missing nginx/sudo or a non-zero exit is a no-op for the caller
    — the block is on disk either way and can be reloaded by hand. Passwordless
    reload needs a sudoers entry (NOPASSWD: /usr/sbin/nginx -s reload)."""
    try:
        r = subprocess.run(
            ["sudo", "nginx", "-s", "reload"],
            check=False, capture_output=True, text=True,
        )
    except FileNotFoundError:
        return False
    return r.returncode == 0


_NGINX_CONFIG_ROOTS = (
    "/etc/nginx/nginx.conf",
    "/etc/nginx/conf.d",
    "/etc/nginx/sites-enabled",
)


def _nginx_config_includes(proxy_dir: str, roots: tuple[str, ...] = _NGINX_CONFIG_ROOTS) -> bool:
    """Best-effort: does the nginx config tree `include` this workspace's _proxy dir?

    Root-free scan of the usual config roots for an include directive referencing
    proxy_dir. Returns True when such an include is found OR when no config is
    readable at all (can't tell — don't cry wolf); False only when config *was*
    read and none of it references the dir. A workspace-local block is useless if
    nginx never includes it (the common owm-legacy → rewrite transition gap), so
    callers use this to warn instead of silently writing an ignored block."""
    needle = os.path.abspath(proxy_dir)
    saw_config = False
    for root in roots:
        paths = [root] if os.path.isfile(root) else (
            [os.path.join(root, n) for n in sorted(os.listdir(root))]
            if os.path.isdir(root) else []
        )
        for path in paths:
            try:
                with open(path) as f:
                    text = f.read()
            except OSError:
                continue
            saw_config = True
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("include") and needle in s:
                    return True
    return not saw_config


class NginxBackend:
    scheme = "http"

    def write_instance(
        self, name: str, http_port: int, gevent_port: int,
        domain_suffix: str, workspace_root: str,
    ) -> None:
        upstream = name.replace("-", "_")
        block = (
            f"upstream {upstream} {{ server 127.0.0.1:{http_port}; }}\n"
            f"upstream {upstream}_lp {{ server 127.0.0.1:{gevent_port}; }}\n"
            f"server {{\n"
            f"    listen 80;\n"
            f"    server_name {name}.{domain_suffix};\n"
            f"\n"
            f"    proxy_read_timeout 720s;\n"
            f"    proxy_set_header X-Forwarded-Host $host;\n"
            f"    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            f"    proxy_set_header X-Forwarded-Proto $scheme;\n"
            f"    proxy_set_header X-Real-IP $remote_addr;\n"
            f"\n"
            f"    location / {{ proxy_pass http://{upstream}; }}\n"
            f"    location /websocket {{ proxy_pass http://{upstream}_lp; }}\n"
            f"    location /longpolling {{ proxy_pass http://{upstream}_lp; }}\n"
            f"}}\n"
        )
        # Workspace-local: blocks live in _proxy/ and are pulled into nginx by the
        # one-time include stub that `owm init` writes (`include _proxy/*.nginx.conf`).
        # The .nginx.conf suffix MUST match that stub's glob, or nginx never loads them.
        proxy_dir = os.path.join(workspace_root, "_proxy")
        os.makedirs(proxy_dir, exist_ok=True)
        with open(os.path.join(proxy_dir, f"{name}.nginx.conf"), "w") as f:
            f.write(block)
        if not _nginx_reload():
            print(
                f"warning: proxy block for {name!r} written but `nginx -s reload` did not "
                f"apply — the block is on disk but nginx is serving its old config, so "
                f"{name}.{domain_suffix} is not live yet. Run `sudo nginx -s reload` (or add a "
                f"NOPASSWD sudoers entry for `/usr/sbin/nginx -s reload`).",
                file=sys.stderr,
            )
        elif not _nginx_config_includes(proxy_dir):
            print(
                f"warning: proxy block for {name!r} written to {proxy_dir}/, but no nginx "
                f"`include` references that dir — nginx will not serve {name}.{domain_suffix} "
                f"until the include is wired (see the stub from `owm init`: "
                f"{proxy_dir}/owm-include.conf).",
                file=sys.stderr,
            )

    def remove_instance(self, name: str, workspace_root: str) -> None:
        path = os.path.join(workspace_root, "_proxy", f"{name}.nginx.conf")
        if os.path.exists(path):
            os.remove(path)
        if not _nginx_reload():
            print(
                f"warning: proxy block for {name!r} removed but `nginx -s reload` did not "
                f"apply — run `sudo nginx -s reload` to stop serving it.",
                file=sys.stderr,
            )


class CaddyBackend:
    scheme = "https"

    def __init__(self, caddy_config: str | None = None) -> None:
        raw = caddy_config or "~/.config/caddy/Caddyfile"
        self._caddy_config = os.path.expanduser(raw)

    def write_instance(
        self, name: str, http_port: int, gevent_port: int,
        domain_suffix: str, workspace_root: str,
    ) -> None:
        block = (
            f"{name}.{domain_suffix} {{\n"
            f"    reverse_proxy /websocket* localhost:{gevent_port} {{\n"
            f"        header_up Origin {{http.request.header.Origin}}\n"
            f"    }}\n"
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

    def _reload(self) -> bool:
        """Best-effort `caddy reload` so a written/removed block takes effect.
        Never raises (the block is on disk either way), but surfaces failure to
        stderr instead of reporting a false success: a non-zero reload — most
        often an ambiguous/invalid site elsewhere in the Caddyfile — leaves the
        running caddy on its old config, so the instance silently isn't served.
        Returns whether the reload actually applied."""
        if not os.path.exists(self._caddy_config):
            print(
                f"warning: caddy config {self._caddy_config} not found — proxy block "
                f"written but not reloaded; caddy is not serving this instance.",
                file=sys.stderr,
            )
            return False
        try:
            r = subprocess.run(
                ["caddy", "reload", "--config", self._caddy_config],
                check=False, capture_output=True, text=True,
            )
        except FileNotFoundError:
            print(
                "warning: caddy not found on PATH — proxy block written but not reloaded.",
                file=sys.stderr,
            )
            return False
        if r.returncode != 0:
            detail = (r.stderr or r.stdout or "").strip()
            print(
                f"warning: caddy reload failed (exit {r.returncode}) — the proxy block is "
                f"on disk but the running caddy kept its old config, so this instance is "
                f"not being served. Fix the Caddyfile and rerun `caddy reload`."
                + (f"\n  {detail}" if detail else ""),
                file=sys.stderr,
            )
            return False
        return True


def get_proxy_backend(proxy_conf) -> ProxyBackend | None:
    if proxy_conf is None:
        return None
    backend = getattr(proxy_conf, "backend", "nginx")
    if backend == "caddy":
        return CaddyBackend(getattr(proxy_conf, "caddy_config", None))
    return NginxBackend()
