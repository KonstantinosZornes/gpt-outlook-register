// 团子喵的 WebUI 交互逻辑 ~

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ──────────────────────── 工具 ────────────────────────

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || resp.statusText);
  return data;
}

function fmtTime(ts) {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
}

function logLine(text, kind = "") {
  const box = $("#logBox");
  const div = document.createElement("div");
  div.className = "line " + kind;
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function classifyLog(line) {
  const l = line.toLowerCase();
  if (l.includes("error") || l.includes("失败") || l.includes("拒绝")) return "err";
  if (l.includes("warning") || l.includes("warn")) return "warn";
  if (l.includes("成功") || l.includes("完成") || l.includes("命中") || l.includes("ok")) return "ok";
  return "";
}

// ──────────────────────── 统计栏 ────────────────────────

async function refreshStats() {
  try {
    const { stats } = await api("/api/stats");
    const items = [
      { v: stats.total,     cls: "" },
      { v: stats.available, cls: "ok" },
      { v: stats.in_use,    cls: "warn" },
      { v: stats.done,      cls: "done" },
      { v: stats.failed,    cls: "bad" },
    ];
    $$("#statsBar .pill").forEach((el, i) => {
      el.querySelector("b").textContent = items[i].v;
    });
  } catch (e) {
    console.error("stats:", e);
  }
}

// ──────────────────────── 导入 ────────────────────────

$("#btnImport").addEventListener("click", async () => {
  const text = $("#importText").value.trim();
  if (!text) {
    $("#importResult").textContent = "请输入要导入的接码号";
    return;
  }
  $("#btnImport").disabled = true;
  $("#importResult").textContent = "导入中...";
  try {
    const r = await api("/api/import", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    $("#importResult").textContent =
      `✅ 解析 ${r.parsed} 行，新增 ${r.inserted}，更新 ${r.updated}，跳过 ${r.skipped}`;
    $("#importResult").className = "result ok";
    $("#importText").value = "";
    refreshStats();
    refreshPool();
  } catch (e) {
    $("#importResult").textContent = "❌ " + e.message;
    $("#importResult").className = "result bad";
  } finally {
    $("#btnImport").disabled = false;
  }
});

// ──────────────────────── 触发注册 ────────────────────────

let currentEs = null;

$("#btnRun").addEventListener("click", async () => {
  const email = $("#regEmail").value.trim();
  const opts = {
    email: email || null,
    proxy: $("#regProxy").value.trim(),
    otp_timeout: parseInt($("#regOtpTimeout").value || "180", 10),
    want_access_token: true,
    want_session_token: false,
    want_refresh_token: false,
  };
  $("#btnRun").disabled = true;
  $("#runStatus").textContent = "启动中...";
  $("#runStatus").className = "result";
  $("#logBox").innerHTML = "";

  try {
    const r = await api("/api/register", {
      method: "POST",
      body: JSON.stringify(opts),
    });
    $("#runStatus").textContent = `🚀 已启动 run_id=${r.run_id} email=${r.email}`;
    logLine(`[client] 启动注册 run_id=${r.run_id} email=${r.email}`, "evt");
    streamRun(r.run_id);
  } catch (e) {
    $("#runStatus").textContent = "❌ " + e.message;
    $("#runStatus").className = "result bad";
    $("#btnRun").disabled = false;
  }
});

function streamRun(runId) {
  if (currentEs) { try { currentEs.close(); } catch (_) {} }
  const es = new EventSource(`/api/runs/${runId}/stream`);
  currentEs = es;

  es.addEventListener("log", (e) => {
    try {
      const d = JSON.parse(e.data);
      if (!d.line) return;
      logLine(d.line, classifyLog(d.line));
    } catch (_) {}
  });

  es.addEventListener("status", (e) => {
    try {
      const d = JSON.parse(e.data);
      if (d.kind === "done") {
        const s = `✅ 注册完成: access_token=${d.access_token_len}${d.partial ? "  (部分凭证)" : ""}`;
        const buttons = [];
        if (d.access_token_len > 0)  buttons.push(`<button class="quick-copy" data-email="${d.email}" data-field="access_token">📋 复制 access_token</button>`);
        $("#runStatus").innerHTML = `<span class="ok">${s}</span>${buttons.length ? "<br>" + buttons.join(" ") : ""}`;
        logLine("[client] " + s, "evt");
      } else if (d.kind === "error") {
        $("#runStatus").textContent = "❌ " + d.message;
        $("#runStatus").className = "result bad";
        logLine("[client] ❌ " + d.message, "err");
      } else if (d.kind === "phase") {
        logLine(`[client] phase=${d.phase} email=${d.email}`, "evt");
      }
    } catch (_) {}
  });

  es.addEventListener("end", () => {
    try { es.close(); } catch (_) {}
    currentEs = null;
    $("#btnRun").disabled = false;
    refreshStats();
    refreshPool();
    refreshRegistered();
    refreshRuns();
  });

  es.onerror = () => {
    try { es.close(); } catch (_) {}
    currentEs = null;
    $("#btnRun").disabled = false;
  };
}

// 状态栏快捷复制按钮（注册完成后直接显示在这里，不用切 Tab）
$("#runStatus").addEventListener("click", async (e) => {
  const copyBtn = e.target.closest("button.quick-copy");
  if (copyBtn) {
    const email = copyBtn.dataset.email;
    const field = copyBtn.dataset.field;
    try {
      const cred = await _loadCred(email);
      const val = cred[field] || "";
      if (!val) { alert(`${field} 为空`); return; }
      await _copyText(val, copyBtn);
    } catch (err) { alert("加载凭证失败: " + err.message); }
  }
});

// ──────────────────────── Tabs ────────────────────────

$$(".tab").forEach((t) => {
  t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $$(".tab-content").forEach((c) => c.classList.add("hidden"));
    $("#tab-" + t.dataset.tab).classList.remove("hidden");
    if (t.dataset.tab === "registered") refreshRegistered();
    if (t.dataset.tab === "runs") refreshRuns();
  });
});

// ──────────────────────── 号池列表 ────────────────────────

async function refreshPool() {
  const status = $("#poolFilter").value;
  const { items } = await api(`/api/accounts?status=${encodeURIComponent(status)}`);
  const tb = $("#poolTable tbody");
  tb.innerHTML = "";
  for (const r of items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.email}</td>
      <td><span class="status ${r.status}">${r.status}</span></td>
      <td title="${r.fail_reason || ''}">${(r.fail_reason || '').slice(0, 50)}</td>
      <td>
        <button data-act="use" data-email="${r.email}">使用</button>
        <button data-act="del" data-email="${r.email}">删除</button>
      </td>
    `;
    tb.appendChild(tr);
  }
}
$("#btnRefreshPool").addEventListener("click", refreshPool);
$("#poolFilter").addEventListener("change", refreshPool);

$("#poolTable").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const email = btn.dataset.email;
  if (btn.dataset.act === "use") {
    $("#regEmail").value = email;
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (btn.dataset.act === "del") {
    if (!confirm(`删除 ${email}？`)) return;
    await api(`/api/accounts/${encodeURIComponent(email)}`, { method: "DELETE" });
    refreshPool();
    refreshStats();
  }
});

// ──────────────────────── 注册结果列表 ────────────────────────

async function refreshRegistered() {
  const { items } = await api("/api/registered");
  const tb = $("#regTable tbody");
  tb.innerHTML = "";
  for (const r of items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.email}</td>
      <td>${r.at_len > 0 ? `<button class="copy-cell" data-email="${r.email}" data-field="access_token" title="点击复制 access_token">✅ ${r.at_len} 📋</button>` : "—"}</td>
      <td>${fmtTime(r.created_at)}</td>
      <td><button data-act="view" data-email="${r.email}">查看凭证</button></td>
    `;
    tb.appendChild(tr);
  }
}
$("#btnRefreshReg").addEventListener("click", refreshRegistered);

// 缓存最近查看的凭证（用于"复制全部 JSON"按钮和单字段复制）
let _credCache = null;

async function _loadCred(email) {
  if (_credCache && _credCache.email === email) return _credCache;
  const { data } = await api(`/api/registered/${encodeURIComponent(email)}`);
  _credCache = data;
  return data;
}

async function _copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      const orig = btn.textContent;
      const cls = btn.className;
      btn.textContent = "✅ 已复制";
      btn.className = cls + " copied";
      setTimeout(() => { btn.textContent = orig; btn.className = cls; }, 1200);
    }
  } catch (e) {
    alert("复制失败: " + e.message);
  }
}

$("#regTable").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const email = btn.dataset.email;
  if (!email) return;

  // 行内快捷复制（access/session/refresh 列直接点）
  if (btn.classList.contains("copy-cell")) {
    const field = btn.dataset.field;
    try {
      const cred = await _loadCred(email);
      const val = cred[field] || "";
      if (!val) { alert(`${field} 为空`); return; }
      await _copyText(val, btn);
    } catch (err) { alert("加载凭证失败: " + err.message); }
    return;
  }

  // 「查看凭证」打开模态框
  if (btn.dataset.act === "view") {
    try {
      const cred = await _loadCred(email);
      _renderCredModal(email, cred);
    } catch (err) { alert("加载凭证失败: " + err.message); }
  }
});


function _renderCredModal(email, cred) {
  $("#credTitle").textContent = email;
  const box = $("#credFields");
  box.innerHTML = "";

  // 主要凭证按顺序展示，每项独立复制按钮
  const KEYS = [
    ["access_token",  "access_token"],
    ["session_token", "session_token"],
    ["refresh_token", "refresh_token"],
    ["id_token",      "id_token"],
    ["device_id",     "device_id"],
    ["csrf_token",    "csrf_token"],
    ["cookie_header", "cookie_header"],
    ["password",      "password"],
  ];
  for (const [key, label] of KEYS) {
    const val = cred[key] || "";
    if (!val) continue;
    const row = document.createElement("div");
    row.className = "cred-row";
    row.innerHTML = `
      <div class="cred-row-head">
        <span class="cred-label">${label}</span>
        <span class="cred-meta">len=${val.length}</span>
        <button class="cred-copy" data-val-key="${key}">📋 复制</button>
      </div>
      <pre class="cred-val">${escapeHtml(val)}</pre>
    `;
    box.appendChild(row);
  }

  // extra（含 cookie 同步等其他元数据）
  if (cred.extra && Object.keys(cred.extra).length > 0) {
    const row = document.createElement("div");
    row.className = "cred-row";
    row.innerHTML = `
      <div class="cred-row-head">
        <span class="cred-label">extra</span>
        <span class="cred-meta">${Object.keys(cred.extra).length} keys</span>
        <button class="cred-copy" data-val-key="__extra__">📋 复制 JSON</button>
      </div>
      <pre class="cred-val">${escapeHtml(JSON.stringify(cred.extra, null, 2))}</pre>
    `;
    box.appendChild(row);
  }

  $("#credModal").classList.remove("hidden");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// 模态框内单字段复制
$("#credFields").addEventListener("click", async (e) => {
  const btn = e.target.closest("button.cred-copy");
  if (!btn) return;
  const key = btn.dataset.valKey;
  const val = key === "__extra__"
    ? JSON.stringify(_credCache.extra, null, 2)
    : (_credCache[key] || "");
  await _copyText(val, btn);
});

$("#credClose").addEventListener("click", () => {
  $("#credModal").classList.add("hidden");
});
$("#credCopyJson").addEventListener("click", async (e) => {
  if (!_credCache) return;
  await _copyText(JSON.stringify(_credCache, null, 2), e.currentTarget);
});

// ──────────────────────── 运行记录 ────────────────────────

async function refreshRuns() {
  const { items } = await api("/api/runs");
  const tb = $("#runTable tbody");
  tb.innerHTML = "";
  for (const r of items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><code>${r.run_id}</code></td>
      <td>${r.email}</td>
      <td><span class="status ${r.status === 'done' ? 'done' : r.status === 'failed' ? 'failed' : 'running'}">${r.status}</span></td>
      <td>${fmtTime(r.started_at)}</td>
      <td title="${r.error || ''}">${(r.error || '').slice(0, 60)}</td>
    `;
    tb.appendChild(tr);
  }
}
$("#btnRefreshRuns").addEventListener("click", refreshRuns);

// ──────────────────────── 🤖 Auto-Loop 全自动批量 ────────────────────────

const AUTO_BTNS = {
  start:  $("#btnAutoStart"),
  pause:  $("#btnAutoPause"),
  resume: $("#btnAutoResume"),
  stop:   $("#btnAutoStop"),
};

function _autoOptions() {
  return {
    proxy: $("#regProxy").value.trim(),
    otp_timeout: parseInt($("#regOtpTimeout").value || "180", 10),
    want_access_token: true,
    want_session_token: false,
    want_refresh_token: false,
    cool_down_seconds: parseFloat($("#autoCoolDown").value || "3") || 0,
  };
}

async function autoStart() {
  try {
    await api("/api/auto/start", { method: "POST", body: JSON.stringify(_autoOptions()) });
  } catch (e) { alert("启动失败: " + e.message); }
}
async function autoCall(path) {
  try { await api(path, { method: "POST" }); }
  catch (e) { alert(`${path} 失败: ${e.message}`); }
}
AUTO_BTNS.start.addEventListener("click", autoStart);
AUTO_BTNS.pause.addEventListener("click", () => autoCall("/api/auto/pause"));
AUTO_BTNS.resume.addEventListener("click", () => autoCall("/api/auto/resume"));
AUTO_BTNS.stop.addEventListener("click", () => autoCall("/api/auto/stop"));

function _renderAutoStatus(s) {
  const stateLabel = {
    "stopped": "⚪ 未运行",
    "running": "🟢 运行中",
    "paused":  "⏸ 已暂停",
  }[s.state] || s.state;
  const elapsed = s.elapsed ? Math.round(s.elapsed) + "s" : "—";
  $("#autoStatus").innerHTML = `
    <b>${stateLabel}</b>
    &nbsp;|&nbsp; 已完成: <b class="ok">${s.registered_ok}</b> 成功 / <b class="bad">${s.registered_fail}</b> 失败
    &nbsp;|&nbsp; 运行: ${elapsed}
    ${s.current_email ? `&nbsp;|&nbsp; 正在: <code>${escapeHtml(s.current_email)}</code>` : ""}
    <br><span class="auto-msg">${escapeHtml(s.last_message || "")}</span>
  `;
  // 按钮可用性
  const st = s.state;
  AUTO_BTNS.start.disabled  = (st === "running" || st === "paused");
  AUTO_BTNS.pause.disabled  = (st !== "running");
  AUTO_BTNS.resume.disabled = (st !== "paused");
  AUTO_BTNS.stop.disabled   = (st === "stopped");
}

let _autoEs = null;
function _connectAutoStream() {
  if (_autoEs) { try { _autoEs.close(); } catch (_) {} }
  const es = new EventSource("/api/auto/stream");
  _autoEs = es;
  es.addEventListener("state", (e) => {
    try { _renderAutoStatus(JSON.parse(e.data)); } catch (_) {}
  });
  es.addEventListener("run_started", (e) => {
    try {
      const d = JSON.parse(e.data);
      logLine(`[auto] ▶ 开始注册 ${d.email} (run=${d.run_id})`, "evt");
      // 复用单跑的 SSE 流，自动接管日志框 + 状态栏复制按钮
      streamRun(d.run_id);
    } catch (_) {}
  });
  es.addEventListener("run_finished", (e) => {
    try {
      const d = JSON.parse(e.data);
      logLine(`[auto] ${d.ok ? "✅" : "❌"} ${d.email} 完成`, d.ok ? "ok" : "err");
    } catch (_) {}
  });
  es.onerror = () => {
    // 自动重连
    try { es.close(); } catch (_) {}
    _autoEs = null;
    setTimeout(_connectAutoStream, 2000);
  };
}

// ──────────────────────── 表单持久化（localStorage 自动保存/恢复）────────────────────────

const FORM_KEY = "gpt_outlook_register_form_v1";

// id -> 类型（默认 text；checkbox 走 .checked）
const PERSIST_FIELDS = {
  regProxy:      "text",
  regOtpTimeout: "text",
  autoCoolDown:  "text",
};

function _saveForm() {
  const data = {};
  for (const [id, kind] of Object.entries(PERSIST_FIELDS)) {
    const el = document.getElementById(id);
    if (!el) continue;
    data[id] = kind === "check" ? !!el.checked : (el.value || "");
  }
  try { localStorage.setItem(FORM_KEY, JSON.stringify(data)); } catch (_) {}
}

function _loadForm() {
  let data = {};
  try { data = JSON.parse(localStorage.getItem(FORM_KEY) || "{}"); } catch (_) { data = {}; }
  for (const [id, kind] of Object.entries(PERSIST_FIELDS)) {
    if (!(id in data)) continue;
    const el = document.getElementById(id);
    if (!el) continue;
    if (kind === "check") el.checked = !!data[id];
    else el.value = data[id] || "";
  }
}

// 绑定 input/change 自动保存
function _bindAutoSave() {
  for (const id of Object.keys(PERSIST_FIELDS)) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.addEventListener("input", _saveForm);
    el.addEventListener("change", _saveForm);
  }
}

// ──────────────────────── 启动 ────────────────────────

_loadForm();
_bindAutoSave();
refreshStats();
refreshPool();
_connectAutoStream();
setInterval(refreshStats, 5000);
