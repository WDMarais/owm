"use strict";

// ── State ──────────────────────────────────────────────────────────────────

let _selectedInstance = null;
let _activeTab        = "owm";

// ── Helpers ────────────────────────────────────────────────────────────────

const _esc = s => String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

// ── Boot ───────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
    await loadStatus();

    document.getElementById("fetch-btn").addEventListener("click", doFetch);

    document.getElementById("actions-btn").addEventListener("click", e => {
        e.stopPropagation();
        document.getElementById("actions-menu").classList.toggle("hidden");
    });
    document.addEventListener("click", () => {
        document.getElementById("actions-menu").classList.add("hidden");
    });

    document.querySelector(".nav-item[data-page='processes']")
        .addEventListener("click", e => { e.preventDefault(); showProcessesPage(); });
});

// ── API helpers ────────────────────────────────────────────────────────────

async function api(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
}

// ── Left pane: status ──────────────────────────────────────────────────────

async function loadStatus() {
    const data = await api("/api/status");
    renderInstanceList(data.instances);
    renderRepoList(data.repos);
    if (data.instances.length > 0) {
        selectInstance(data.instances[0].name);
    }
    loadNotifications();
    loadBanner();
    setInterval(loadNotifications, 30_000);
}

async function doFetch() {
    const btn = document.getElementById("fetch-btn");
    btn.disabled = true;
    btn.textContent = "Fetching…";
    try {
        await fetch("/api/fetch", { method: "POST" });
        const data = await api("/api/status");
        renderRepoList(data.repos);
        await loadNotifications();
    } catch (_) {}
    btn.textContent = "Fetch";
    btn.disabled = false;
}

async function loadBanner() {
    try {
        const data = await api("/api/banner");
        renderBanner(data.alerts);
    } catch (_) {}
}

function renderBanner(alerts) {
    const banner = document.getElementById("header-banner");
    const items  = document.getElementById("banner-items");
    items.innerHTML = "";
    if (!alerts || !alerts.length) {
        banner.classList.add("hidden");
        return;
    }
    for (const a of alerts) {
        const el = document.createElement("div");
        el.className = `banner-item ${a.level}`;
        el.innerHTML = `<span class="banner-icon">${a.level === "critical" ? "✕" : "⚠"}</span>
                        <span class="banner-msg">${_esc(a.msg)}</span>`;
        items.appendChild(el);
    }
    banner.classList.remove("hidden");
}

async function loadNotifications() {
    try {
        const data = await api("/api/notifications");
        renderNotifications(data.notifications);
    } catch (_) {}
}

function renderNotifications(notifications) {
    const section = document.getElementById("notifications-section");
    section.innerHTML = `<div class="section-label">Notifications<button class="btn-notif-refresh" title="Refresh notifications">↻</button></div>`;
    section.querySelector(".btn-notif-refresh").addEventListener("click", loadNotifications);

    const scroll = document.createElement("div");
    scroll.className = "notif-scroll";

    if (!notifications.length) {
        const el = document.createElement("div");
        el.className = "notif-empty";
        el.textContent = "all clear";
        scroll.appendChild(el);
    } else {
        for (const n of notifications) {
            const el = document.createElement("div");
            el.className = `notif-row ${n.tier}`;
            el.innerHTML = `<span class="notif-content">
                              ${n.instance ? `<span class="notif-tag">[${_esc(n.instance)}]</span>` : ""}${_esc(n.msg)}
                            </span>`;
            el.addEventListener("click", () => _notifPivot(n));
            scroll.appendChild(el);
        }
    }

    section.appendChild(scroll);
}

function _notifPivot(n) {
    if (n.section === "processes" && !n.instance) {
        showProcessesPage();
        return;
    }
    if (n.instance && n.instance !== _selectedInstance) {
        selectInstance(n.instance, n.section);
    } else {
        _scrollToSection(n.section);
    }
}

function _scrollToSection(section) {
    if (!section) return;
    const cards = document.querySelectorAll("#centre-pane .card");
    for (const card of cards) {
        const title = card.querySelector(".card-title");
        if (title && title.textContent.trim().toLowerCase() === section.toLowerCase()) {
            card.scrollIntoView({ behavior: "smooth", block: "nearest" });
            card.classList.remove("highlight");
            void card.offsetWidth; // reflow to restart animation
            card.classList.add("highlight");
            setTimeout(() => card.classList.remove("highlight"), 1100);
            return;
        }
    }
}

function renderInstanceList(instances) {
    const section = document.querySelector(".nav-section-instances");
    section.innerHTML = '<div class="section-label">Instances</div>';
    for (const inst of instances) {
        const el = document.createElement("div");
        el.className = "instance-item";
        el.dataset.instance = inst.name;
        el.innerHTML = `<span class="dot dot-${inst.status === "running" ? "running" : "stopped"}"></span>
                        <span class="instance-name">${_esc(inst.name)}</span>`;
        el.addEventListener("click", () => selectInstance(inst.name));
        section.appendChild(el);
    }
}

function renderRepoList(repos) {
    const section = document.querySelector(".nav-section-remotes");
    section.innerHTML = '<div class="section-label">Remotes</div>';
    for (const repo of repos) {
        const stale = repo.last_fetch && (repo.last_fetch.includes("h") || repo.last_fetch.includes("d"));
        const el = document.createElement("div");
        el.className = `repo-item${stale ? " stale" : ""}`;
        el.innerHTML = `<span class="repo-name">${_esc(repo.name)}</span>
                        <span class="repo-age">${_esc(repo.last_fetch ?? "—")}</span>`;
        section.appendChild(el);
    }
}

// ── Instance selection ─────────────────────────────────────────────────────

async function selectInstance(name, scrollTo = null, restoreTab = null) {
    _selectedInstance = name;

    document.getElementById("centre-pane").classList.remove("hidden");
    document.getElementById("processes-page").classList.add("hidden");

    document.querySelectorAll(".instance-item").forEach(el => {
        el.classList.toggle("active", el.dataset.instance === name);
    });
    document.querySelector(".nav-item[data-page='processes']").classList.remove("active");

    const data = await api(`/api/instance/${name}`);
    renderCentre(data, restoreTab);
    if (scrollTo) _scrollToSection(scrollTo);
}

// ── Centre pane ────────────────────────────────────────────────────────────

function renderCentre(inst, restoreTab = null) {
    renderNavbar(inst);
    renderCommands(inst);
    renderHealth(inst);
    renderScripts(inst);
    renderRepos(inst);
    renderTabStrip(inst, restoreTab);
}

// ── Top navbar: instance dock ──────────────────────────────────────────────

function renderNavbar(inst) {
    const dock = document.getElementById("instance-dock");
    dock.classList.remove("hidden");

    document.getElementById("dock-name").textContent = inst.name;

    const statusEl = document.getElementById("dock-status");
    statusEl.textContent = inst.status === "running"
        ? `running · pid ${inst.pid}`
        : inst.status;
    statusEl.className = `status-badge ${inst.status}`;

    const urlEl = document.getElementById("dock-url");
    const url = `https://${inst.name}.localhost`;
    urlEl.href = url;
    urlEl.textContent = url;

    const metaEl = document.getElementById("dock-meta");
    metaEl.textContent = inst.started_at ? `started ${inst.started_at}` : "";

    const actionsEl = document.getElementById("dock-actions");
    actionsEl.innerHTML = "";
    const running = inst.status === "running";

    const mkBtn = (label, action, cls) => {
        const btn = document.createElement("button");
        btn.className = `btn-dock ${cls}`;
        btn.textContent = label;
        btn.addEventListener("click", () => _instanceAction(inst.name, action, btn));
        return btn;
    };

    if (running) {
        actionsEl.appendChild(mkBtn("Stop",    "stop",    "btn-stop"));
        actionsEl.appendChild(mkBtn("Restart", "restart", "btn-restart"));
        actionsEl.appendChild(mkBtn("Kill",    "kill",    "btn-kill"));
    } else {
        actionsEl.appendChild(mkBtn("Start",   "start",   "btn-start"));
    }

    _renderActionsMenu(inst);
}

function _renderActionsMenu(inst) {
    const menu = document.getElementById("actions-menu");
    menu.innerHTML = "";

    const running = inst.status === "running";

    const mkItem = (label, fn, disabled = false) => {
        const el = document.createElement("button");
        el.className = "action-item";
        el.textContent = label;
        if (disabled) {
            el.disabled = true;
            el.title = "Stop the instance first";
        } else {
            el.addEventListener("click", () => {
                document.getElementById("actions-menu").classList.add("hidden");
                fn();
            });
        }
        return el;
    };

    menu.appendChild(mkItem("Rename…", () => {
        const newName = window.prompt(`Rename "${inst.name}" to:`, inst.name);
        if (!newName || newName === inst.name) return;
        fetch(`/api/instance/${inst.name}/rename?new_name=${encodeURIComponent(newName)}`, { method: "POST" })
            .then(() => loadStatus());
    }, running));

    menu.appendChild(mkItem("Archive", () => {
        if (!window.confirm(`Archive "${inst.name}"?`)) return;
        fetch(`/api/instance/${inst.name}/archive`, { method: "POST" })
            .then(() => loadStatus());
    }, running));

    menu.appendChild(mkItem("Delete…", () => {
        if (!window.confirm(`Delete "${inst.name}"? This cannot be undone.`)) return;
        fetch(`/api/instance/${inst.name}/delete`, { method: "POST" })
            .then(() => loadStatus());
    }, running));
}

async function _instanceAction(name, action, btn) {
    const prev    = btn.textContent;
    const prevTab = _activeTab;
    btn.disabled  = true;
    btn.textContent = action.charAt(0).toUpperCase() + action.slice(1) + "…";
    try {
        await fetch(`/api/instance/${name}/${action}`, { method: "POST" });
        await selectInstance(name, null, prevTab);
    } catch (_) {
        btn.textContent = prev;
        btn.disabled = false;
    }
}

function renderHealth(inst) {
    const grid = document.querySelector(".health-grid");
    grid.innerHTML = "";
    const stopped = inst.status === "stopped";
    const items = [
        ["HTTP",   inst.health.http],
        ["Gevent", inst.health.gevent],
        ["DB",     inst.health.db],
        ["Venv",   inst.health.venv],
        ["Proxy",  inst.health.proxy],
    ];
    for (const [label, h] of items) {
        if (!h) continue;
        const stateClass = stopped && !h.ok ? "muted" : h.ok ? "ok" : "err";
        const el = document.createElement("div");
        el.className = "health-item";
        el.innerHTML = `<span class="health-label">${_esc(label)}</span>
                        <span class="health-value ${stateClass}">${_esc(h.value)}</span>`;
        grid.appendChild(el);
    }
}

function renderScripts(inst) {
    const list = document.querySelector(".script-list");
    list.innerHTML = "";
    if (!inst.scripts.length) {
        const el = document.createElement("div");
        el.className = "script-empty";
        el.textContent = "no scripts configured";
        list.appendChild(el);
        return;
    }
    for (const s of inst.scripts) {
        const badgeClass = s.status === "ok"  ? "badge-ok"
                         : s.status === "fail" ? "badge-fail"
                         : "badge-none";
        const el = document.createElement("div");
        el.className = "script-row";
        el.innerHTML = `
            <div class="script-name-line">
              <span class="script-name">${_esc(s.name)}</span>
              <button class="btn-run" data-script="${_esc(s.name)}">Run</button>
            </div>
            <div class="script-meta-line">
              <span class="badge ${badgeClass}">${_esc(s.status ?? "—")}</span>
              <span class="script-time">${_esc(s.last_run ?? "never")}</span>
            </div>`;
        list.appendChild(el);
    }
}

function _syncSummary(repo) {
    const issues = [];
    if (repo.dirty) issues.push({label: "uncommitted changes", state: "dirty", canSync: false});

    if (!repo.has_remote) {
        issues.push({label: "local only", state: "local", canSync: false});
        return issues;
    }

    const vob    = repo.vs_origin_branch             ?? {};
    const obob   = repo.origin_branch_vs_origin_base ?? {};
    const behind = vob.behind_by  ?? 0;
    const ahead  = vob.ahead_by   ?? 0;
    const remoteBehindBase = obob.behind_by ?? 0;
    const ref = `origin/${repo.branch}`;

    if (behind > 0 && ahead > 0) issues.push({label: `${ahead} ahead, ${behind} behind ${ref}`, state: "err", canSync: false});
    else {
        if (behind > 0) issues.push({label: `${behind} behind ${ref}`,  state: "behind", canSync: true});
        if (ahead  > 0) issues.push({label: `${ahead} unpushed`,        state: "ahead",  canSync: false});
    }
    if (remoteBehindBase > 0) issues.push({label: `origin/${repo.branch} ${remoteBehindBase} behind ${repo.base ?? "base"}`, state: "behind", canSync: true});
    if (issues.length === 0) issues.push({label: "up to date", state: "clean", canSync: false});
    return issues;
}

function renderRepos(inst) {
    const list = document.querySelector(".repo-list");
    list.innerHTML = "";
    for (const repo of inst.repos) {
        const issues = _syncSummary(repo);
        const canSync = issues.some(i => i.canSync);
        const lc = repo.last_commit;
        const commitLine = (!repo.has_remote && lc)
            ? `<div class="repo-commit-line" title="${_esc(lc.ts ?? "")}">${_esc(lc.hash)}${lc.rel ? " · " + _esc(lc.rel) : ""}</div>`
            : "";
        const syncLines = issues.map(i =>
            `<div class="repo-sync-line"><span class="sync-state ${i.state}">${_esc(i.label)}</span></div>`
        ).join("");
        const el = document.createElement("div");
        el.className = "repo-row";
        el.innerHTML = `
            <div class="repo-name-line">
              <span class="repo-name-group">
                <span class="repo-name">${_esc(repo.name)}</span><span class="repo-branch" title="${_esc(repo.branch ?? "")}"> (${_esc(repo.branch ?? "")})</span>
              </span>
              ${canSync ? `<button class="btn-sync" data-repo="${_esc(repo.name)}">Sync</button>` : ""}
            </div>
            ${syncLines}${commitLine}`;

        if (canSync) {
            el.querySelector(".btn-sync").addEventListener("click", async e => {
                const btn = e.target;
                btn.disabled = true;
                btn.textContent = "Syncing…";
                await fetch(`/api/instance/${_selectedInstance}/sync/${encodeURIComponent(repo.name)}`, { method: "POST" });
                await selectInstance(_selectedInstance);
            });
        }

        el.querySelector(".repo-branch").addEventListener("click", e => {
            const span = e.currentTarget;
            navigator.clipboard.writeText(repo.branch ?? "").then(() => {
                const prev = span.textContent;
                span.textContent = " ✓";
                setTimeout(() => { span.textContent = prev; }, 1000);
            });
        });

        list.appendChild(el);
    }
}

function renderCommands(inst) {
    const list = document.querySelector(".cmd-list");
    list.innerHTML = "";
    for (const cmd of inst.commands) {
        const el = document.createElement("div");
        el.className = "cmd-row";
        el.dataset.cmd = cmd.cmd;
        el.innerHTML = `<span class="cmd-label">${_esc(cmd.label)}</span>
                        <code class="cmd-value" title="${_esc(cmd.cmd)}">${_esc(cmd.cmd)}</code>`;
        list.appendChild(el);
    }
    list.addEventListener("click", e => {
        const row = e.target.closest(".cmd-row");
        if (!row) return;
        navigator.clipboard.writeText(row.dataset.cmd).then(() => {
            const val = row.querySelector(".cmd-value");
            val.classList.add("copied");
            setTimeout(() => val.classList.remove("copied"), 1200);
        });
    });
}

// ── Processes page ─────────────────────────────────────────────────────────

async function showProcessesPage() {
    _closeStream();
    document.getElementById("centre-pane").classList.add("hidden");
    document.getElementById("processes-page").classList.remove("hidden");

    document.querySelectorAll(".instance-item").forEach(el => el.classList.remove("active"));
    document.querySelector(".nav-item[data-page='processes']").classList.add("active");

    const strip = document.querySelector(".tab-strip");
    strip.innerHTML = "";
    strip.appendChild(_makeTab({ key: "owm", label: "owm.log", cls: "" }));
    strip.appendChild(_makeWrapToggle());
    _activateTab("owm");

    const data = await api("/api/processes");
    renderProcesses(data);
}

function renderProcesses(data) {
    const page = document.getElementById("processes-page");
    page.innerHTML = '<div class="page-header"><h2>Processes</h2></div>';

    _renderProcessSection(page, "Managed",                   data.managed,      _managedRow);
    _renderProcessSection(page, "Orphaned owm processes",    data.orphaned,     _orphanedRow);
    _renderProcessSection(page, "Unregistered (owm-shaped)", data.unregistered, _unregisteredRow);
    _renderProcessSection(page, "Port squatters",            data.squatters,    _squatterRow);
}

function _renderProcessSection(page, label, rows, rowFn) {
    if (!rows.length) return;
    const sec = document.createElement("div");
    sec.className = "process-section";
    sec.innerHTML = `<div class="section-label">${_esc(label)}</div>`;
    for (const r of rows) sec.appendChild(rowFn(r));
    page.appendChild(sec);
}

function _pill(port, label) {
    return label
        ? `<span class="port-pill"><span class="port-label">${_esc(label)}</span>:${_esc(port)}</span>`
        : `<span class="port-pill">:${_esc(port)}</span>`;
}

function _managedRow(p) {
    const el = document.createElement("div");
    el.className = "process-row";
    const pills = [p.http && _pill(p.http, "http"), p.gevent && _pill(p.gevent, "gevent")]
        .filter(Boolean).join("");
    const hasWorkers = p.workers && p.workers.length > 0;
    const toggleId   = `workers-${p.pid}`;

    let workersHtml = "";
    if (hasWorkers) {
        const rows = p.workers.map(w =>
            `<div class="worker-row">
               <span class="worker-type" data-type="${_esc(w.type)}">${_esc(w.type)}</span>
               <span class="proc-pid">pid ${_esc(w.pid)}</span>
             </div>`
        ).join("");
        workersHtml = `<div class="worker-list hidden" id="${_esc(toggleId)}">${rows}</div>`;
    }

    el.innerHTML = `
        <div class="proc-name-line">
          <span class="dot dot-${p.status === "running" ? "running" : "stopped"}"></span>
          <a class="proc-name proc-name-link" title="${_esc(p.name)}">${_esc(p.name)}</a>
          ${hasWorkers ? `<button class="btn-workers" data-target="${_esc(toggleId)}">${p.workers.length} workers</button>` : ""}
        </div>
        <div class="proc-detail-line">
          <span class="proc-ports">${pills}</span>
          ${p.pid ? `<span class="proc-pid">pid ${_esc(p.pid)}</span>` : ""}
        </div>
        ${workersHtml}`;

    el.querySelector(".proc-name-link").addEventListener("click", () => selectInstance(p.name));

    if (hasWorkers) {
        el.querySelector(".btn-workers").addEventListener("click", e => {
            const list = document.getElementById(e.target.dataset.target);
            list.classList.toggle("hidden");
            e.target.classList.toggle("active");
        });
    }

    return el;
}

function _orphanedRow(p) {
    const el = document.createElement("div");
    el.className = "process-row";
    const pills = p.ports.map(n => _pill(n, null)).join("");
    el.innerHTML = `
        <div class="proc-name-line">
          <span class="dot dot-warn"></span>
          <span class="proc-name" title="${_esc(p.name)}">${_esc(p.name)}</span>
        </div>
        <div class="proc-detail-line">
          <span class="proc-ports">${pills}</span>
          <span class="proc-pid">pid ${_esc(p.pid)}</span>
          <button class="btn-readopt" data-pid="${_esc(p.pid)}">Re-adopt</button>
        </div>`;
    return el;
}

function _unregisteredRow(p) {
    const el = document.createElement("div");
    el.className = "process-row";
    const pills = p.ports.map(n => _pill(n, null)).join("");
    el.innerHTML = `
        <div class="proc-name-line">
          <span class="dot dot-warn"></span>
          <span class="proc-name" title="${_esc(p.cmd)}">${_esc(p.cmd)}</span>
        </div>
        <div class="proc-detail-line">
          <span class="proc-ports">${pills}</span>
          <span class="proc-pid">pid ${_esc(p.pid)}</span>
          <button class="btn-adopt-flow" data-pid="${_esc(p.pid)}">Adopt…</button>
        </div>`;
    return el;
}

function _squatterRow(p) {
    const el = document.createElement("div");
    el.className = "process-row";
    const pills = p.ports.map(n => _pill(n, null)).join("");
    el.innerHTML = `
        <div class="proc-name-line">
          <span class="dot dot-err"></span>
          <span class="proc-name" title="${_esc(p.cmd)}">${_esc(p.cmd)}</span>
        </div>
        <div class="proc-detail-line">
          <span class="proc-ports">${pills}</span>
          <span class="proc-pid">pid ${_esc(p.pid)}</span>
          <span class="proc-note">not owm-managed</span>
        </div>`;
    return el;
}

// ── Right pane: logs ───────────────────────────────────────────────────────

let _activeStream = null;

function _closeStream() {
    if (_activeStream) { _activeStream.close(); _activeStream = null; }
}

function _streamUrl(key) {
    if (key === "owm")  return "/api/logs/owm/stream";
    if (key === "odoo") return `/api/logs/${_selectedInstance}/odoo/stream`;
    return null;
}

function _makeWrapToggle() {
    const wrap = document.createElement("button");
    wrap.className = "tab-wrap-toggle";
    wrap.textContent = "wrap";
    wrap.title = "Toggle line wrapping";
    const viewport = document.querySelector(".log-viewport");
    wrap.addEventListener("click", () => {
        const on = viewport.classList.toggle("nowrap");
        wrap.classList.toggle("active", !on);
    });
    return wrap;
}

function renderTabStrip(inst, restoreTab = null) {
    const strip = document.querySelector(".tab-strip");
    strip.innerHTML = "";

    strip.appendChild(_makeTab({ key: "owm", label: "owm.log", cls: "" }));

    const sep = document.createElement("span");
    sep.className = "tab-sep";
    sep.textContent = inst.name;
    strip.appendChild(sep);

    strip.appendChild(_makeTab({ key: "odoo", label: "odoo.log", cls: "" }));
    for (const s of inst.scripts) {
        strip.appendChild(_makeTab({ key: `script:${s.name}`, label: s.name, cls: "tab-runner" }));
    }

    strip.appendChild(_makeWrapToggle());
    _activateTab(restoreTab ?? "owm");
}

function _makeTab(t) {
    const btn = document.createElement("button");
    btn.className = `tab${t.cls ? " " + t.cls : ""}`;
    btn.dataset.tab = t.key;
    btn.textContent = t.label;
    btn.addEventListener("click", () => _activateTab(t.key));
    return btn;
}

function _activateTab(key) {
    _activeTab = key;
    document.querySelectorAll(".tab-strip .tab").forEach(el => {
        el.classList.toggle("active", el.dataset.tab === key);
    });
    _loadTabLogs(key);
}

async function _loadTabLogs(key) {
    _closeStream();
    const viewport = document.querySelector(".log-viewport");

    if (key.startsWith("script:")) {
        viewport.innerHTML = `<div class="log-line log-info">— runner log not yet available —</div>`;
        return;
    }

    try {
        const logUrl = key === "owm" ? `/api/logs/owm` : `/api/logs/${_selectedInstance}/odoo`;
        const data = await api(logUrl);
        _renderLogLines(data.lines);
    } catch (e) {
        viewport.innerHTML = `<div class="log-line log-err">${_esc(e.message)}</div>`;
        return;
    }

    const streamUrl = _streamUrl(key);
    if (!streamUrl) return;

    const src = new EventSource(streamUrl);
    _activeStream = src;
    src.onmessage = e => {
        const line   = JSON.parse(e.data);
        const text   = (line.text ?? "").replace(_ANSI_RE, "");
        const cls    = _levelClass(line.level ?? _detectLevel(text));
        const prefix = line.ts ? `[${line.ts.slice(11, 19)}] ` : "";
        const el     = document.createElement("div");
        el.className = `log-line${cls ? " " + cls : ""}`;
        el.textContent = prefix + text;
        const atBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 60;
        viewport.appendChild(el);
        if (atBottom) viewport.scrollTop = viewport.scrollHeight;
    };
    src.onerror = () => { src.close(); if (_activeStream === src) _activeStream = null; };
}

const _ANSI_RE = /\x1b\[[0-9;]*m/g;

function _renderLogLines(lines) {
    const viewport = document.querySelector(".log-viewport");
    viewport.innerHTML = "";
    for (const line of lines) {
        const text   = (line.text ?? "").replace(_ANSI_RE, "");
        const cls    = _levelClass(line.level ?? _detectLevel(text));
        const prefix = line.ts ? `[${line.ts.slice(11, 19)}] ` : "";
        const el     = document.createElement("div");
        el.className = `log-line${cls ? " " + cls : ""}`;
        el.textContent = prefix + text;
        viewport.appendChild(el);
    }
    viewport.scrollTop = viewport.scrollHeight;
}

function _levelClass(level) {
    if (!level) return "";
    const l = level.toLowerCase();
    if (l === "warning" || l === "warn") return "log-warn";
    if (l === "error"   || l === "err")  return "log-err";
    if (l === "ok"      || l === "success") return "log-ok";
    return "log-info";
}

function _detectLevel(text) {
    if (/\bERROR\b/.test(text))             return "err";
    if (/\bWARNING\b|\bWARN\b/.test(text)) return "warn";
    if (/\bINFO\b/.test(text))             return "info";
    return "";
}
