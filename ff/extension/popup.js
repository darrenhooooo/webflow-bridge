/* Webflow Bridge for Firefox — companion 控制面板 popup 逻辑
 * MV2 · 无后台页：popup 打开期间每 2s 轮询本地 daemon（127.0.0.1:10096）。
 * 主卡 = 整卡状态显示器（终版，整卡即按钮 role=button）：中性灰 Checking…
 *（探测中）/ 红底 Inactive「未激活」（点开「激活清单」逐项补齐）/ 绿底
 * Active「已激活」（点击做一次真实 evaluate → 友好绿卡确认，不回显标题）。
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

// i18n：共享语言包（i18n.js 先于此文件加载）。技术词（daemon/token/BiDi 等）
// 与命令/路径保持原样；动态文案一律走 T(key[, vars])，占位符 {…} 在调用处注入。
const T = (k, vars) => window.WBF_I18N.t(k, vars);

// 平台 / 启动器事实（与 ff/README.md「启动 ff daemon」/「启动 Firefox」一致，
// 绝不虚构）：Windows 用 README 里的真实 Python 3.11+ 示例路径。
const PLATFORM = String((navigator.userAgentData && navigator.userAgentData.platform) ||
                        navigator.platform || '');
const IS_WIN = /^win/i.test(PLATFORM);
const DAEMON_CMD = IS_WIN
  ? 'C:/Users/darre/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe ff/daemon/ff_bridge.py'
  : 'python3 ff/daemon/ff_bridge.py';
const DAEMON_UV_CMD = 'uv run --python 3.11 ff/daemon/ff_bridge.py';
const FF_LAUNCH_CMD = IS_WIN ? 'ff\\ff-launch.bat' : 'ff/ff-launch.sh';

const $ = (id) => document.getElementById(id);

/* ---------- 快捷操作失败引导卡（动作失败时显示修复步骤） ---------- */
// kind：'daemon' = daemon 离线；'ext' = POST 被 403（Origin 拦，需重载/重启 daemon）；
//       'fx' = daemon 在跑但 Firefox（BiDi 9222）未连接（503）。
// 仅用于执行 JS / 取页面 / 列标签页等快捷操作；激活入口的失败由「激活清单」覆盖。
// 文案里的命令与 ff/README.md / 面板「启动指引」一致。

// 引导卡 step 文案 key（语言包里 guide_d_1.. / guide_e_1.. / guide_f_1..）。
const GUIDE_STEP_KEYS = {
  daemon: ['guide_d_1', 'guide_d_2', 'guide_d_3', 'guide_d_4'],
  ext: ['guide_e_1', 'guide_e_2', 'guide_e_3'],
  fx: ['guide_f_1', 'guide_f_2', 'guide_f_3', 'guide_f_4'],
};

// 引导卡 / 启动指引里出现代码与路径处用占位符注入（值都是常量，非文案）。
function guideVars() {
  return {
    repo: 'C:/Users/darre/Desktop/webflow',
    dcmd: DAEMON_CMD,
    dcmd_unix: 'python3 ff/daemon/ff_bridge.py',
    uv: DAEMON_UV_CMD,
    launch: FF_LAUNCH_CMD,
    lw: 'ff\\ff-launch.bat',
    lm: 'ff/ff-launch.sh',
  };
}

function setGuide(kind) {
  $('act-guide').dataset.kind = kind;
  $('actDot').dataset.state = kind === 'fx' ? 'warn' : 'down';
  $('guideTitle').textContent = T('guide_title_' + kind);
  const list = $('guideSteps');
  list.textContent = '';
  const keys = GUIDE_STEP_KEYS[kind] || [];
  const vars = guideVars();
  for (const k of keys) {
    const li = document.createElement('li');
    li.innerHTML = T(k, vars);
    list.appendChild(li);
  }
  $('act-guide').hidden = false;
}

function hideGuide() { $('act-guide').hidden = true; }

// 把动作失败归类到引导卡级别；返回 kind，非基础设施类失败返回 null（照旧显示文本）。
function classifyFail(p) {
  if (!p) return null;
  if (p.net) return 'daemon';
  if (p.http === 403) return 'ext';
  if (p.http === 503) return 'fx';
  return null;
}

let lastFail = null;   // {kind, fn, tab} 「重试」时复跑上次失败的动作

function routeFail(p, fn, tab) {
  const kind = classifyFail(p);
  if (!kind) return false;
  $('result').hidden = true;           // 清掉「执行中…」占位
  setGuide(kind);
  lastFail = { kind: kind, fn: fn, tab: tab };
  return true;
}

async function retryLast() {
  hideGuide();
  const f = lastFail;
  lastFail = null;
  await poll();                        // 先刷新 daemon / Firefox 状态
  if (!f) return;
  if (f.fn === 'exec') await doExec();
  else if (f.fn === 'pageinfo') await currentPage();
  else if (f.fn === 'tabs') await listTabs();
  else if (f.fn === 'tab') await queryTabTitle(f.tab);
}

let token = null;        // 内存缓存的 bearer token（daemon /config 提供）
let daemonUp = null;     // null=未知 true/false
let bridgeInfo = null;   // probe 结果（含 connected / firefox 版本）
let bridgeErr = '';
let polling = false;

// 激活入口主卡状态机（终版）：'checking' | 'inactive' | 'active'
let actState = 'checking';
let actBusy = false;     // 验证/诊断在途：保持 Checking… 且不可点，防 updateActBtn 覆盖

/* ---------- 激活清单（方案A）行内容 ---------- */

const ROW_NAMES = {
  daemon: T('row_daemon'),
  ext: T('row_ext'),
  page: T('row_page'),
};

function rowIcon(rowState) {
  return rowState === 'ok' ? '✓'
       : rowState === 'bad' ? '✗'
       : rowState === 'busy' ? '·' : '…';
}

function truncate(text, max) {
  const s = String(text);
  return s.length > max ? s.slice(0, max) + '…' : s;
}

// 修复内容构建器（仅 'bad' 行使用；静态模板文案走 innerHTML，动态错误走 textContent）。
// 极简引导句 + 带标签的命令行（平台命令 / uv，各带复制）。
function daemonFix() {
  const fix = [];
  fix.push({ type: 'text', html: T('daemon_lead') });
  fix.push({ type: 'cmd', label: T('cmd_python'), cmd: DAEMON_CMD });
  fix.push({ type: 'cmd', label: T('cmd_uv'), cmd: DAEMON_UV_CMD });
  fix.push({ type: 'text', html: T('daemon_fix_wait') });
  return fix;
}

function extFix() {
  const fix = [];
  fix.push({ type: 'text', html: T('ext_fix_1') });
  fix.push({ type: 'text', html: T('ext_fix_2') });
  fix.push({ type: 'text', html: T('ext_fix_3') });
  return fix;
}

// 页面行修复：按真实失败分类（503/Firefox 未连 → ff-launch；其余 → 切普通网页）。
function pageFix(p) {
  const low = String((p && p.error) || '').toLowerCase();
  const isFxDown = (p && p.http === 503) ||
                   /firefox 未连接|firefox not connected|没有.*bidi.*会话/.test(low);
  const fix = [];
  if (isFxDown) {
    fix.push({ type: 'text', html: T('pagefix_fx_1', { launch: FF_LAUNCH_CMD }) });
    fix.push({ type: 'text', html: T('pagefix_fx_2') });
    fix.push({ type: 'text', html: T('pagefix_fx_3') });
    fix.push({ type: 'text', html: T('press_recheck') });
  } else {
    fix.push({ type: 'text', html: T('pagefix_gen_1') });
    fix.push({ type: 'text', html: T('pagefix_gen_2') });
    fix.push({ type: 'text', html: T('press_recheck') });
  }
  if (p && p.error) fix.push({ type: 'raw', text: truncate(p.error, 120) });
  return fix;
}

function addRow(name, rowState, fix) {
  const li = document.createElement('li');
  li.className = 'wiz-row';
  li.dataset.state = rowState;

  const line = document.createElement('div');
  line.className = 'wiz-line';
  const icon = document.createElement('span');
  icon.className = 'wiz-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = rowIcon(rowState);
  const label = document.createElement('span');
  label.className = 'wiz-name';
  label.textContent = name;
  line.appendChild(icon);
  line.appendChild(label);
  li.appendChild(line);

  if (fix && fix.length) {
    const box = document.createElement('div');
    box.className = 'wiz-fix';
    for (const item of fix) {
      if (item.type === 'text') {
        const el = document.createElement('div');
        el.className = 'wiz-step';
        el.innerHTML = item.html;            // 静态模板文案
        box.appendChild(el);
      } else if (item.type === 'cmd') {
        const row = document.createElement('div');
        row.className = 'wiz-cmd';
        if (item.label) {
          const lb = document.createElement('span');
          lb.className = 'wiz-cmd-label';
          lb.textContent = item.label;
          row.appendChild(lb);
        }
        const code = document.createElement('code');
        code.textContent = item.cmd;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'copy-btn';
        btn.dataset.cmd = item.cmd;
        btn.textContent = T('copy');
        btn.addEventListener('click', () => copyCmd(btn));
        row.appendChild(code);
        row.appendChild(btn);
        box.appendChild(row);
      } else if (item.type === 'note') {
        const el = document.createElement('div');
        el.className = 'wiz-note';
        el.textContent = item.text;
        box.appendChild(el);
      } else if (item.type === 'raw') {
        const el = document.createElement('code');
        el.className = 'wiz-rawerr';
        el.textContent = item.text;          // 动态错误 — 只用 textContent
        box.appendChild(el);
      }
    }
    li.appendChild(box);
  }
  $('wizRows').appendChild(li);
}

function renderRows(rows) {
  const list = $('wizRows');
  list.textContent = '';
  for (const key of ['daemon', 'ext', 'page']) {
    const r = rows[key];
    addRow(ROW_NAMES[key], r.state,
           r.fix || (r.note ? [{ type: 'note', text: r.note }] : null));
  }
}

function showWizard() { $('wizard').hidden = false; }
function hideWizard() { $('wizard').hidden = true; }

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
    return { ok: false, net: true, error: T('net_error', { e: (e && e.name) ? e.name : String(e) }) };
  }
  if (res.http === 401) {            // token 轮换过：重取一次
    token = await fetchConfig();
    if (token) {
      try { res = await tryPost(token); }
      catch (e) { return { ok: false, net: true, error: T('net_error', { e: (e && e.name) ? e.name : String(e) }) }; }
    }
  }
  if (res.http === 403) {
    return { ok: false, http: 403, error: T('err_403') };
  }
  if (res.http === 503) {
    return { ok: false, http: 503, error: T('err_503') };
  }
  const b = res.body || {};
  if (res.http !== 200) {
    return { ok: false, http: res.http, error: 'HTTP ' + res.http + ' ' + JSON.stringify(b) };
  }
  if (b.status === 'error') {
    return { ok: false, error: b.error || T('err_daemon') };
  }
  if (b.status !== 'ok') {
    return { ok: false, error: T('err_unknown_resp') + JSON.stringify(b) };
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

// 主卡下方仅有 bridgeErr 小字（可选）：终版把 daemon / Firefox 细粒度状态灯
// 移除，状态语义整体由整卡承担（灰 Checking… / 红 Inactive / 绿 Active），
// 明细交给「激活清单」；此处只在异常时补一行错误原文。
function renderStatus() {
  const err = $('status-err');
  if (bridgeErr && daemonUp) {
    err.textContent = T('last_error_prefix') + bridgeErr;
    err.hidden = false;
  } else {
    err.hidden = true;
  }

  const copyBtn = $('btn-copy-token');
  copyBtn.disabled = !daemonUp;
  $('token-hint').textContent = daemonUp ? T('token_hint_on') : T('token_hint_off');
  if (!daemonUp) renderToken(null);
  updateActBtn();          // 主卡 Checking…/Inactive/Active 随真实状态刷新
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

/* ---------- 激活入口主卡（终版：整卡状态显示器） ---------- */

function setActBtn(s) {
  actState = s;
  const c = $('mainCard');
  c.dataset.state = s;
  c.setAttribute('aria-disabled', (s === 'checking') ? 'true' : 'false');
  $('mainWord').textContent = (s === 'checking') ? T('checking')
                             : (s === 'active') ? T('active') : T('inactive');
}

// 由真实状态推导：daemon 在线 + Firefox 已连（probe connected）→ Active；
// 首轮探测未回 / daemon 在但 probe 未返回 → Checking…；其余 → Inactive（红底）。
function updateActBtn() {
  if (actBusy) return;
  if (daemonUp && bridgeInfo && bridgeInfo.connected === true) {
    setActBtn('active');
  } else if (daemonUp === null ||
             (daemonUp && bridgeInfo === null && bridgeErr === '')) {
    setActBtn('checking');
  } else {
    setActBtn('inactive');
  }
}

/* ---------- 激活清单诊断（逐行真值，绝不虚构） ---------- */
// 每次诊断都实时 fetch /config + POST probe + （必要时）evaluate 一次。
// `evHint`（可选）：Active 点击刚失败的 evaluate 结果 —— 复用为 page 行结论，
// 避免重复 evaluate；daemon/Firefox 层错误仍由本次 probe 重新判定。

async function runDiagnosis(evHint) {
  showWizard();
  const list = $('wizRows');
  list.textContent = '';
  for (const key of ['daemon', 'ext', 'page']) {
    addRow(ROW_NAMES[key], 'busy', null);
  }

  const tk = await fetchConfig();
  const up = tk !== null;
  if (up && tk) token = tk;
  daemonUp = up;
  bridgeInfo = null;
  bridgeErr = '';
  renderStatus();

  if (!up) {
    const note = T('note_daemon_off');
    renderRows({
      daemon: { state: 'bad', fix: daemonFix() },
      ext: { state: 'pending', note: note },
      page: { state: 'pending', note: note },
    });
    return;
  }

  const probe = await postCommand('probe', {});
  if (probe.net) {
    daemonUp = false; bridgeInfo = null; bridgeErr = '';
    renderStatus();
    const note = T('note_daemon_off');
    renderRows({
      daemon: { state: 'bad', fix: daemonFix() },
      ext: { state: 'pending', note: note },
      page: { state: 'pending', note: note },
    });
    return;
  }
  if (probe.http === 403) {
    daemonUp = true; bridgeInfo = null; bridgeErr = probe.error || '';
    renderStatus();
    renderRows({
      daemon: { state: 'ok' },
      ext: { state: 'bad', fix: extFix() },
      page: { state: 'pending', note: T('note_ext_rejected') },
    });
    return;
  }
  if (probe.http === 503 || (probe.ok && probe.data && probe.data.connected !== true)) {
    daemonUp = true;
    bridgeInfo = (probe.ok && probe.data) ? probe.data : null;
    bridgeErr = probe.error || '';
    renderStatus();
    renderRows({
      daemon: { state: 'ok' },
      ext: { state: 'ok' },
      page: { state: 'bad', fix: pageFix({ http: 503, error: T('err_503') }) },
    });
    return;
  }
  if (!probe.ok) {
    // 其它 HTTP 错误（daemon 内部异常）→ 归到 page 行并展示原始错误
    daemonUp = true; bridgeInfo = null; bridgeErr = probe.error || '';
    renderStatus();
    renderRows({
      daemon: { state: 'ok' },
      ext: { state: 'ok' },
      page: { state: 'bad', fix: pageFix(probe) },
    });
    return;
  }

  // probe 200 + connected：真实 evaluate 一次证明当前标签页可驱动
  daemonUp = true; bridgeInfo = probe.data; bridgeErr = '';
  renderStatus();
  let ev;
  if (evHint) {
    ev = evHint;                       // Active 点击刚失败过，不重复 evaluate
  } else {
    ev = await postCommand('evaluate', { code: '(() => document.title)()' });
  }
  if (ev && ev.ok) {
    renderRows({ daemon: { state: 'ok' }, ext: { state: 'ok' }, page: { state: 'ok' } });
    hideWizard();                      // 全部 ✓ → 主卡转绿底 Active
    return;
  }
  renderRows({
    daemon: { state: 'ok' },
    ext: { state: 'ok' },
    page: { state: 'bad', fix: pageFix(ev || { error: T('unknown_error') }) },
  });
}

// 主卡点击：Inactive（红底）→ 打开激活清单并诊断；Active（绿底）→ 真实 evaluate
// 验证通道（成功显示友好绿卡，不回显 document.title；失败落入激活清单对应行）。
async function activateBtn() {
  hideGuide();
  hideWizard();
  if (actBusy || actState === 'checking') return;
  $('result').hidden = true;

  if (actState === 'inactive') {
    await runDiagnosis();
    return;
  }

  actBusy = true;
  setActBtn('checking');
  const p = await postCommand('evaluate', { code: '(() => document.title)()' });
  actBusy = false;
  updateActBtn();
  if (p.ok) {
    showTestOk(T('test_ok'));
    return;
  }
  await runDiagnosis(p);       // probe 一次；真实错误落到 daemon/ext/page 对应行
}

/* ---------- 通用结果渲染 ---------- */

function showResult(text, isErr) {
  const pre = $('result');
  pre.classList.toggle('err', !!isErr);
  pre.classList.remove('ok');
  pre.textContent = text;
  pre.hidden = false;
}

// Active 验证通过 → 友好绿卡（不回显页面标题）。
function showTestOk(text) {
  const pre = $('result');
  pre.classList.remove('err');
  pre.classList.add('ok');
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
  catch (e) { showResult(T('internal_error_prefix') + (e && e.message || e), true); }
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
  hideGuide();
  const code = getCode();
  if (!code.trim()) { showResult(T('exec_empty'), true); return; }
  if (!daemonUp) { routeFail({ net: true, error: T('err_daemon') + ' (offline)' }, 'exec'); return; }
  showResult(T('exec_busy'));
  const p = await postCommand('evaluate', { code: code });
  saveHistory(code);
  if (p.ok) { showResult(fmtValue(p.data)); return; }
  if (!routeFail(p, 'exec')) showResult('✗ ' + p.error, true);
}

/* ---------- 快捷操作 ---------- */

/* 取当前页标题/URL：优先取可见(active)标签页，否则第一个顶层 context */
async function currentPage() {
  hideGuide();
  if (!daemonUp) { routeFail({ net: true, error: T('err_daemon') + ' (offline)' }, 'pageinfo'); return; }
  showResult(T('fetching'));
  const list = await postCommand('tabs_list', {});
  if (!list.ok) { if (routeFail(list, 'pageinfo')) return; showResult('✗ ' + list.error, true); return; }
  const entries = Array.isArray(list.data) ? list.data : [];
  if (!entries.length) { showResult(T('no_top_tabs'), true); return; }
  let target = entries.find((t) => t && t.active === true);
  if (!target) target = entries[0];
  const p = await postCommand('evaluate', {
    code: '(() => ({ title: document.title, url: location.href }))()',
    tabId: target.id,
  });
  if (!p.ok) { if (routeFail(p, 'pageinfo')) return; showResult('✗ ' + p.error, true); return; }
  const info = p.data || {};
  const box = $('pageinfo');
  box.innerHTML = '';
  const title = document.createElement('div');
  const tb = document.createElement('b'); tb.textContent = T('label_title');
  title.appendChild(tb); title.appendChild(document.createTextNode(String(info.title || '')));
  const url = document.createElement('div');
  const ub = document.createElement('b'); ub.textContent = T('label_url');
  url.appendChild(ub); url.appendChild(document.createTextNode(String(info.url || '')));
  box.appendChild(title); box.appendChild(url);
  box.hidden = false;
  showResult(T('label_title') + info.title + '\n' + T('label_url') + info.url);
}

async function listTabs() {
  hideGuide();
  if (!daemonUp) { routeFail({ net: true, error: T('err_daemon') + ' (offline)' }, 'tabs'); return; }
  const p = await postCommand('tabs_list', {});
  if (!p.ok) { if (routeFail(p, 'tabs')) return; showResult('✗ ' + p.error, true); return; }
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
    title.textContent = t.title || T('untitled');
    const url = document.createElement('div');
    url.className = 't-url';
    url.textContent = t.url || '';
    const meta = document.createElement('div');
    meta.className = 't-meta';
    meta.textContent = (t.active ? T('visible_prefix') : '') + T('ctx_label', { id: String(t.id).slice(0, 10) }) + '…';
    if (t.active) meta.classList.add('t-active');
    li.appendChild(title); li.appendChild(url); li.appendChild(meta);
    li.title = T('tab_click_hint');
    li.addEventListener('click', () => queryTabTitle(t));
    ul.appendChild(li);
  }
}

async function queryTabTitle(tab) {
  hideGuide();
  if (!daemonUp) { routeFail({ net: true, error: T('err_daemon') + ' (offline)' }, 'tab', tab); return; }
  const p = await postCommand('evaluate', { code: 'document.title', tabId: tab.id });
  if (p.ok) { showResult(T('tab_title_result', { id: tab.id, title: fmtValue(p.data) })); return; }
  if (!routeFail(p, 'tab', tab)) showResult('✗ ' + p.error, true);
}

/* ---------- 剪贴板与复制 ---------- */

async function clipboardWrite(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) { /* fall through */ }
  // 兜底：execCommand（需要用户手势，按钮点击满足）
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
  ta.remove();
  return ok;
}

async function copyCmd(btn) {
  if (btn.disabled) return;
  const ok = await clipboardWrite(btn.dataset.cmd || '');
  const prev = btn.textContent;
  btn.textContent = ok ? T('copied') : T('copy_failed');
  btn.classList.toggle('copied', ok);
  btn.disabled = true;
  setTimeout(() => {
    btn.textContent = prev;
    btn.classList.remove('copied');
    btn.disabled = false;
  }, 1500);
}

/* ---------- token 复制 ---------- */

async function copyToken() {
  const t = await fetchConfig();
  if (!t) { showResult(T('token_off_err'), true); return; }
  token = t;
  renderToken(t);
  const okText = T('copied');
  const btn = $('btn-copy-token');
  const old = btn.textContent;
  const ok = await clipboardWrite(t);
  if (!ok) { showResult(T('copy_fail_perm'), true); return; }
  btn.textContent = okText;
  setTimeout(() => { btn.textContent = old; }, 1200);
  showResult(T('token_copied'));
}

/* ---------- 启动 ---------- */

function wire() {
  $('btn-exec').addEventListener('click', () => guardExec(doExec));
  $('btn-clear').addEventListener('click', () => { $('exec-code').value = ''; });
  $('mainCard').addEventListener('click', () => guardExec(activateBtn));
  $('mainCard').addEventListener('keydown', (ev) => {
    // role=button：回车 / 空格等同点击整卡。
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      guardExec(activateBtn);
    }
  });
  $('btn-pageinfo').addEventListener('click', () => guardExec(currentPage));
  $('btn-tabs').addEventListener('click', () => guardExec(listTabs));
  $('btn-copy-token').addEventListener('click', () => guardExec(copyToken));
  $('wizRecheck').addEventListener('click', () => guardExec(runDiagnosis));
  $('exec-code').addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') { ev.preventDefault(); guardExec(doExec); }
  });
  $('guideRetry').addEventListener('click', () => guardExec(retryLast));
}

// 「启动指引」<details> 区按语言渲染（代码/路径经占位符注入，与 ff/README.md 一致）。
function renderStartupGuide() {
  const ol = $('startup-guide');
  if (!ol) return;
  ol.textContent = '';
  const vars = guideVars();
  const items = [
    { k: 'guide_start_1', v: { launch: FF_LAUNCH_CMD } },
    { k: 'guide_start_2', v: { dcmd: DAEMON_CMD } },
    { k: 'guide_start_3' },
  ];
  for (const it of items) {
    const li = document.createElement('li');
    li.innerHTML = T(it.k, it.v);
    ol.appendChild(li);
  }
  const p = $('ext-desc');
  if (p) p.innerHTML = T('ext_desc', { doc: 'C:/Users/darre/Desktop/webflow/ff/README.md' });
}

async function init() {
  wire();
  renderStartupGuide();
  // add-on 版本（manifest 常量）：只填头部徽章（唯一一次；端口 / 本地
  // daemon 行已去掉，不再往连接行拼版本）。
  try {
    const ver = (browser.runtime.getManifest() || {}).version;
    if (ver) $('version').textContent = 'v' + ver;
  } catch (_) { /* manifest 不可读则保留占位符 */ }
  renderHistory();
  renderStatus();
  poll();                       // 立即一次
  setInterval(poll, POLL_MS);   // 每 2s
}

document.addEventListener('DOMContentLoaded', () => init());
