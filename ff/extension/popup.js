/* Webflow Bridge for Firefox — companion 控制面板 popup 逻辑
 * MV2 · 无后台页：popup 打开期间每 2s 轮询本地 daemon (http://127.0.0.1:10096)。
 * 驱动能力全部由 daemon 经 WebDriver BiDi 完成；本扩展只做控制面板。
 * 不注入任何页面、不连 BiDi WS、不上传任何数据。
 */
'use strict';

const DAEMON_BASE = 'http://127.0.0.1:10096';
const CONFIG_URL = DAEMON_BASE + '/config';
const COMMAND_URL = DAEMON_BASE + '/command';
const POLL_MS = 2000;
const FETCH_TIMEOUT_MS = 1500;   // health /config 探测超时
const COMMAND_TIMEOUT_MS = 5000; // POST /command 超时
const TOKEN_KEY = 'ffBridgeToken';
const HISTORY_KEY = 'ffExecHistory';
const MAX_HISTORY = 5;

const $ = (id) => document.getElementById(id);

let token = null;        // 内存缓存的 bearer token（daemon /config 提供）
let daemonUp = null;     // null=未知 true/false
let bridgeInfo = null;   // probe 结果（含 connected / firefox 版本）
let bridgeErr = '';
let polling = false;

/* ---------- 基础 fetch（带超时，永不抛出） ---------- */

function fetchWithTimeout(url, opts, ms) {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), ms) : null;
  const o = Object.assign({}, opts || {});
  if (ctl) o.signal = ctl.signal;
  return fetch(url, o).then(
    (r) => { if (timer) clearTimeout(timer); return r; },
    (e) => { if (timer) clearTimeout(timer); throw e; }
  );
}

/* GET /config -> token 字符串 | null（daemon 离线/无响应） */
async function fetchConfig() {
  try {
    const r = await fetchWithTimeout(CONFIG_URL, {}, FETCH_TIMEOUT_MS);
    if (!r.ok) return null;
    const j = await r.json().catch(() => null);
    return (j && typeof j.token === 'string' && j.token) ? j.token : null;
  } catch (_) {
    return null;
  }
}

/* POST /command {action, args}（Bearer 鉴权）。
 * 返回 {ok:true, data} | {ok:false, error, http?, net?} */
async function postCommand(action, args) {
  if (!token) token = await fetchConfig();
  const tryPost = async (bearer) => {
    const r = await fetchWithTimeout(COMMAND_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (bearer || ''),
      },
      body: JSON.stringify({ action: action, args: args || {} }),
    }, COMMAND_TIMEOUT_MS);
    let body = null;
    try { body = await r.json(); } catch (_) { /* keep null */ }
    return { http: r.status, body: body };
  };

  let res;
  try {
    res = await tryPost(token);
  } catch (e) {
    return { ok: false, net: true, error: '无法连接 daemon（' + (e && e.name ? e.name : e) + '）' };
  }
  if (res.http === 401) {            // token 轮换过：重取一次
    token = await fetchConfig();
    if (token) {
      try { res = await tryPost(token); }
      catch (e) { return { ok: false, net: true, error: '无法连接 daemon' }; }
    }
  }
  if (res.http === 403) {
    return { ok: false, http: 403, error: 'daemon 拒绝了跨源 POST（Origin 被拦）' };
  }
  if (res.http === 503) {
    return { ok: false, http: 503, error: 'Firefox 未连接（daemon 在跑但没有 BiDi 会话）' };
  }
  const b = res.body || {};
  if (res.http !== 200) {
    return { ok: false, http: res.http, error: 'HTTP ' + res.http + ' ' + JSON.stringify(b) };
  }
  if (b.status === 'error') {
    return { ok: false, error: b.error || 'daemon 返回错误' };
  }
  if (b.status !== 'ok') {
    return { ok: false, error: '未知响应: ' + JSON.stringify(b) };
  }
  return { ok: true, data: (b.data && 'value' in b.data) ? b.data.value : b.data };
}

/* ---------- 状态轮询 ---------- */

async function poll() {
  if (polling) return;               // 避免 2s 内慢请求重叠
  polling = true;
  const tokenNow = await fetchConfig();
  const up = tokenNow !== null;
  if (up && tokenNow) { token = tokenNow; renderToken(tokenNow); }
  const wasUp = daemonUp;
  daemonUp = up;
  if (!up) { bridgeInfo = null; bridgeErr = ''; }
  renderStatus();

  if (up) {
    // daemon 在：probe Firefox 桥状态（lazy connect，首次可能较慢）
    const p = await postCommand('probe', {});
    if (!p.ok && p.net) {
      daemonUp = false;              // 轮询间隔中 daemon 下线
      bridgeInfo = null;
      bridgeErr = '';
    } else if (p.ok) {
      bridgeInfo = p.data || null;
      bridgeErr = '';
    } else {
      bridgeInfo = null;
      bridgeErr = p.error || '';
    }
    renderStatus();
  } else if (wasUp) {
    bridgeErr = '';
  }
  polling = false;
}

function fmtBridgeDetail() {
  if (!bridgeInfo) return '';
  const parts = [];
  if (bridgeInfo.firefox) parts.push('Firefox ' + bridgeInfo.firefox);
  if (bridgeInfo.sessionId) parts.push('session ' + String(bridgeInfo.sessionId).slice(0, 8) + '…');
  if (Array.isArray(bridgeInfo.contexts)) parts.push(bridgeInfo.contexts.length + ' 个顶层 context');
  return parts.join(' · ');
}

function setDot(id, state) { $(id).dataset.state = state; }

function renderStatus() {
  const de = $('daemon-dot'), dt = $('daemon-text');
  const fe = $('ff-dot'), ft = $('ff-text');
  const err = $('status-err');

  if (daemonUp === null) {
    setDot('daemon-dot', 'busy'); de.title = '';
    dt.textContent = 'daemon 检测中…';
    fe.title = '';
  } else if (daemonUp) {
    setDot('daemon-dot', 'ok'); de.title = 'GET :10096/config 200';
    dt.textContent = 'daemon 运行中';
  } else {
    setDot('daemon-dot', 'down'); de.title = '';
    dt.textContent = 'daemon 离线';
  }

  if (!daemonUp) {
    setDot('ff-dot', 'down'); fe.title = '';
    ft.textContent = 'daemon 离线';
  } else if (bridgeInfo === null && bridgeErr === '') {
    setDot('ff-dot', 'busy'); fe.title = '';
    ft.textContent = '检测 Firefox…';
  } else if (bridgeInfo && bridgeInfo.connected) {
    setDot('ff-dot', 'ok');
    ft.textContent = 'Firefox 已连接';
    fe.title = fmtBridgeDetail();
  } else {
    setDot('ff-dot', 'warn');
    ft.textContent = 'Firefox 未连接';
    fe.title = bridgeErr || 'daemon 在跑但 Firefox（BiDi 9222）不在或会话被占';
  }

  if (bridgeErr && daemonUp) {
    err.textContent = '上次错误: ' + bridgeErr;
    err.hidden = false;
  } else {
    err.hidden = true;
  }

  const copyBtn = $('btn-copy-token');
  copyBtn.disabled = !daemonUp;
  $('token-hint').textContent = daemonUp ? '与 ~/.webflow_bridge_ff/token 一致' : 'daemon 离线时不可用';
  if (!daemonUp) renderToken(null);
}

function renderToken(tok) {
  const el = $('token-text');
  if (!tok) {
    el.textContent = '—';
    el.title = '';
    return;
  }
  el.textContent = tok.length > 12 ? tok.slice(0, 8) + '…' + tok.slice(-4) : tok;
  el.title = tok;
}

/* ---------- 通用结果渲染 ---------- */

function showResult(text, isErr) {
  const pre = $('result');
  pre.classList.toggle('err', !!isErr);
  pre.textContent = text;
  pre.hidden = false;
}

function fmtValue(v) {
  if (v === null || v === undefined) return String(v);
  if (typeof v === 'string') return v;
  try { return JSON.stringify(v, null, 2); }
  catch (_) { return String(v); }
}

async function guardExec(fn) {
  try { await fn(); }
  catch (e) { showResult('内部错误: ' + (e && e.message || e), true); }
}

/* ---------- 执行 JS ---------- */

function getCode() { return $('exec-code').value; }

async function saveHistory(code) {
  if (!code || !code.trim()) return;
  try {
    const store = await browser.storage.local.get(HISTORY_KEY);
    let arr = Array.isArray(store[HISTORY_KEY]) ? store[HISTORY_KEY] : [];
    arr = arr.filter((h) => h && h.code !== code);
    arr.unshift({ code: code, ts: Date.now() });
    if (arr.length > MAX_HISTORY) arr.length = MAX_HISTORY;
    await browser.storage.local.set({ [HISTORY_KEY]: arr });
    renderHistory();
  } catch (_) { /* storage 不可用则不记历史 */ }
}

async function renderHistory() {
  try {
    const store = await browser.storage.local.get(HISTORY_KEY);
    const arr = Array.isArray(store[HISTORY_KEY]) ? store[HISTORY_KEY] : [];
    const box = $('history');
    const list = $('history-list');
    list.textContent = '';
    if (!arr.length) { box.hidden = true; return; }
    for (const h of arr) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'history-chip';
      chip.title = h.code;
      const one = h.code.replace(/\s+/g, ' ').trim();
      chip.textContent = one.length > 42 ? one.slice(0, 42) + '…' : one;
      chip.addEventListener('click', () => { $('exec-code').value = h.code; });
      list.appendChild(chip);
    }
    box.hidden = false;
  } catch (_) { /* ignore */ }
}

async function doExec() {
  const code = getCode();
  if (!code.trim()) { showResult('请输入要执行的 JS', true); return; }
  if (!daemonUp) { showResult('daemon 离线，无法执行', true); return; }
  showResult('执行中…');
  const p = await postCommand('evaluate', { code: code });
  saveHistory(code);
  if (p.ok) showResult(fmtValue(p.data));
  else showResult('✗ ' + p.error, true);
}

/* ---------- 快捷操作 ---------- */

/* 取当前页标题/URL：优先取可见(active)标签页，否则第一个顶层 context */
async function currentPage() {
  if (!daemonUp) { showResult('daemon 离线', true); return; }
  showResult('获取中…');
  const list = await postCommand('tabs_list', {});
  if (!list.ok) { showResult('✗ ' + list.error, true); return; }
  const entries = Array.isArray(list.data) ? list.data : [];
  if (!entries.length) { showResult('✗ Firefox 没有顶层标签页', true); return; }
  let target = entries.find((t) => t && t.active === true);
  if (!target) target = entries[0];
  const p = await postCommand('evaluate', {
    code: '(() => ({ title: document.title, url: location.href }))()',
    tabId: target.id,
  });
  if (!p.ok) { showResult('✗ ' + p.error, true); return; }
  const info = p.data || {};
  const box = $('pageinfo');
  box.innerHTML = '';
  const title = document.createElement('div');
  const tb = document.createElement('b'); tb.textContent = '标题: ';
  title.appendChild(tb); title.appendChild(document.createTextNode(String(info.title || '')));
  const url = document.createElement('div');
  const ub = document.createElement('b'); ub.textContent = 'URL: ';
  url.appendChild(ub); url.appendChild(document.createTextNode(String(info.url || '')));
  box.appendChild(title); box.appendChild(url);
  box.hidden = false;
  showResult('标题: ' + info.title + '\nURL: ' + info.url);
}

async function listTabs() {
  if (!daemonUp) { showResult('daemon 离线', true); return; }
  const p = await postCommand('tabs_list', {});
  if (!p.ok) { showResult('✗ ' + p.error, true); return; }
  const entries = Array.isArray(p.data) ? p.data : [];
  const ul = $('tabs-list');
  const empty = $('tabs-empty');
  ul.textContent = '';
  empty.hidden = entries.length !== 0;
  ul.hidden = entries.length === 0;
  if (!entries.length) return;
  for (const t of entries) {
    const li = document.createElement('li');
    const title = document.createElement('div');
    title.className = 't-title';
    title.textContent = t.title || '(无标题)';
    const url = document.createElement('div');
    url.className = 't-url';
    url.textContent = t.url || '';
    const meta = document.createElement('div');
    meta.className = 't-meta';
    meta.textContent = (t.active ? '● 可见 · ' : '') + 'context ' + String(t.id).slice(0, 10) + '…';
    if (t.active) meta.classList.add('t-active');
    li.appendChild(title); li.appendChild(url); li.appendChild(meta);
    li.title = '点击用该标签页执行 document.title';
    li.addEventListener('click', () => queryTabTitle(t));
    ul.appendChild(li);
  }
}

async function queryTabTitle(tab) {
  if (!daemonUp) return;
  const p = await postCommand('evaluate', { code: 'document.title', tabId: tab.id });
  if (p.ok) showResult('标签页 ' + tab.id + ' 标题: ' + fmtValue(p.data));
  else showResult('✗ ' + p.error, true);
}

/* ---------- token 复制 ---------- */

async function copyToken() {
  const t = await fetchConfig();
  if (!t) { showResult('daemon 离线，无法获取 token', true); return; }
  token = t;
  renderToken(t);
  const okText = '已复制 ✓';
  const btn = $('btn-copy-token');
  const old = btn.textContent;
  try {
    await navigator.clipboard.writeText(t);
  } catch (_) {
    // 兜底：execCommand（需要用户手势，按钮点击满足）
    const ta = document.createElement('textarea');
    ta.value = t;
    ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
    ta.remove();
    if (!ok) { showResult('✗ 复制失败（无剪贴板权限）', true); return; }
  }
  btn.textContent = okText;
  setTimeout(() => { btn.textContent = old; }, 1200);
  showResult('token 已复制到剪贴板');
}

/* ---------- 启动 ---------- */

function wire() {
  $('btn-exec').addEventListener('click', () => guardExec(doExec));
  $('btn-clear').addEventListener('click', () => { $('exec-code').value = ''; });
  $('btn-pageinfo').addEventListener('click', () => guardExec(currentPage));
  $('btn-tabs').addEventListener('click', () => guardExec(listTabs));
  $('btn-copy-token').addEventListener('click', () => guardExec(copyToken));
  $('exec-code').addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') { ev.preventDefault(); guardExec(doExec); }
  });
}

async function init() {
  wire();
  renderHistory();
  renderStatus();
  poll();                       // 立即一次
  setInterval(poll, POLL_MS);   // 每 2s
}

document.addEventListener('DOMContentLoaded', () => init());
