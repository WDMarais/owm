"use strict";

// ── State ──────────────────────────────────────────────────────────────────

let _selectedInstance = null;
let _activeTab        = "owm";

// ── Boot ───────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
    await loadStatus();
    document.getElementById("left-pane").querySelector(".collapse-btn")
        .addEventListener("click", toggleLeftPane);
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

    // Select first instance by default
    if (data.instances.length > 0) {
        selectInstance(data.instances[0].name);
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
                        <span class="instance-name">${inst.name}</span>`;
        el.addEventListener("click", () => selectInstance(inst.name));
        section.appendChild(el);
    }
}

function renderRepoList(repos) {
    const section = document.querySelector(".nav-section-repos");
    section.innerHTML = '<div class="section-label">Repos</div>';
    for (const repo of repos) {
        const stale = repo.last_fetch && (repo.last_fetch.includes("h") || repo.last_fetch.includes("d"));
        const el = document.createElement("div");
        el.className = `repo-item${stale ? " stale" : ""}`;
        el.innerHTML = `<span class="repo-name">${repo.name}</span>
                        <span class="repo-age">${repo.last_fetch ?? "—"}</span>`;
        section.appendChild(el);
    }
}

// ── Instance selection ─────────────────────────────────────────────────────

async function selectInstance(name) {
    _selectedInstance = name;

    // Update left nav active state
    document.querySelectorAll(".instance-item").forEach(el => {
        el.classList.toggle("active", el.dataset.instance === name);
    });

    const data = await api(`/api/instance/${name}`);
    renderCentre(data);
}

// ── Centre pane ────────────────────────────────────────────────────────────

function renderCentre(inst) {
    renderHeader(inst);
    renderHealth(inst);
    renderScripts(inst);
    renderRepos(inst);
    renderCommands(inst);
    renderTabStrip(inst);
}

function renderHeader(inst) {
    const h1 = document.querySelector(".instance-title h1");
    const badge = document.querySelector(".instance-title .status-badge");
    h1.textContent = inst.name;
    badge.textContent = inst.status === "running"
        ? `running · pid ${inst.pid}`
        : inst.status;
    badge.className = `status-badge ${inst.status}`;
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
        // Ports being "not ok" is expected for a stopped instance — mute rather than alarm
        const stateClass = stopped && !h.ok ? "muted" : h.ok ? "ok" : "err";
        const el = document.createElement("div");
        el.className = "health-item";
        el.innerHTML = `<span class="health-label">${label}</span>
                        <span class="health-value ${stateClass}">${h.value}</span>`;
        grid.appendChild(el);
    }
}

function renderScripts(inst) {
    const list = document.querySelector(".script-list");
    list.innerHTML = "";
    for (const s of inst.scripts) {
        const badgeClass = s.status === "ok" ? "badge-ok"
                         : s.status === "fail" ? "badge-fail"
                         : "badge-none";
        const badgeText = s.status ?? "—";
        const el = document.createElement("div");
        el.className = "script-row";
        el.innerHTML = `<span class="badge ${badgeClass}">${badgeText}</span>
                        <span class="script-name">${s.name}</span>
                        <span class="script-time">${s.last_run ?? "never"}</span>
                        <button class="btn-run" data-script="${s.name}">Run</button>`;
        list.appendChild(el);
    }
}

function _syncSummary(repo) {
    // Returns [{label, state, canSync}] — multiple issues possible per repo
    const issues = [];
    const vob     = repo.vs_origin_branch ?? {};
    const vobase  = repo.vs_origin_base   ?? {};
    const behind  = vob.behind_by  ?? 0;
    const ahead   = vob.ahead_by   ?? 0;
    const baseBehind = vobase.behind_by ?? 0;

    if (repo.dirty)              issues.push({label: "uncommitted changes", state: "dirty",  canSync: false});
    if (behind > 0 && ahead > 0) issues.push({label: `diverged (${ahead}↑ ${behind}↓)`, state: "err", canSync: false});
    else {
        if (behind > 0) issues.push({label: `${behind} behind origin`, state: "behind", canSync: true});
        if (ahead  > 0) issues.push({label: `${ahead} unpushed`,       state: "ahead",  canSync: false});
    }
    if (baseBehind > 0) issues.push({label: `${baseBehind} behind base`, state: "behind", canSync: true});
    if (issues.length === 0) issues.push({label: "up to date", state: "clean", canSync: false});
    return issues;
}

function renderRepos(inst) {
    const list = document.querySelector(".repo-list");
    list.innerHTML = "";
    for (const repo of inst.repos) {
        const issues  = _syncSummary(repo);
        const primary = issues[0];
        const extra   = issues.slice(1).map(i => `<span class="sync-state ${i.state}">${i.label}</span>`).join(" · ");
        const label   = extra
            ? `<span class="sync-state ${primary.state}">${primary.label}</span> · ${extra}`
            : `<span class="sync-state ${primary.state}">${primary.label}</span>`;
        const canSync = issues.some(i => i.canSync);
        const el = document.createElement("div");
        el.className = "repo-row";
        el.innerHTML = `<span class="repo-col repo-name">${repo.name}</span>
                        <span class="repo-col branch">${repo.branch}</span>
                        <span class="repo-col sync-state-cell">${label}</span>
                        <span class="repo-col repo-action">${canSync
                            ? `<button class="btn-sync" data-repo="${repo.name}">Sync</button>`
                            : ""}</span>`;
        list.appendChild(el);
    }
}

function renderCommands(inst) {
    const list = document.querySelector(".cmd-list");
    list.innerHTML = "";
    for (const cmd of inst.commands) {
        const el = document.createElement("div");
        el.className = "cmd-row";
        el.innerHTML = `<span class="cmd-label">${cmd.label}</span>
                        <code class="cmd-value">${cmd.cmd}</code>
                        <button class="btn-copy" data-cmd="${cmd.cmd}">Copy</button>`;
        list.appendChild(el);
    }
    list.addEventListener("click", e => {
        const btn = e.target.closest(".btn-copy");
        if (btn) navigator.clipboard.writeText(btn.dataset.cmd).then(() => {
            btn.textContent = "✓";
            setTimeout(() => btn.textContent = "Copy", 1500);
        });
    });
}

// ── Left pane collapse ─────────────────────────────────────────────────────

function toggleLeftPane() {
    const pane = document.getElementById("left-pane");
    const btn  = pane.querySelector(".collapse-btn");
    const collapsed = pane.classList.toggle("collapsed");
    btn.textContent = collapsed ? "›" : "‹";
}

// ── Right pane: logs ───────────────────────────────────────────────────────

function renderTabStrip(inst) {
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

    _activateTab("owm");
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
    const viewport = document.querySelector(".log-viewport");
    if (key.startsWith("script:")) {
        viewport.innerHTML = `<div class="log-line log-info">— runner log not yet available —</div>`;
        return;
    }
    try {
        const data = await api(`/api/logs/${_selectedInstance}/${key}`);
        _renderLogLines(data.lines);
    } catch (e) {
        viewport.innerHTML = `<div class="log-line log-err">${e.message}</div>`;
    }
}

// ANSI CSI escape sequences (colours, bold, reset, etc.)
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

// Detect level from plain-text Odoo log lines: "... INFO ...", "... WARNING ..."
function _detectLevel(text) {
    if (/\bERROR\b/.test(text))              return "err";
    if (/\bWARNING\b|\bWARN\b/.test(text))  return "warn";
    if (/\bINFO\b/.test(text))              return "info";
    return "";
}
