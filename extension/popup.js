// Webflow Bridge popup — whole-card status display (终版主卡).
// The whole main card is the status surface AND the action entry (role=button):
//   neutral grey Checking… (initial probe, not clickable)
//   red Inactive (未激活) — click opens the activation checklist, fix what's
//   missing, Re-check → green Active (已激活) — click runs one real evaluate
//   → friendly confirmation card (no title echo).
// Talks to background.js over chrome.runtime messages (wf-ping / wf-evaluate).
(function () {
  'use strict';

  const MAX_RESULT = 120;

  // Shortcut for the shared i18n map (i18n.js runs before this file).
  const T = (k, vars) => window.WBF_I18N.t(k, vars);

  // Platform / browser facts used to render the real daemon start commands
  // (they mirror README "Start the daemon" — never invented) and the right
  // extension-reload URL.
  const IS_EDGE = /Edg\//.test(navigator.userAgent || '');
  const PLATFORM = String((navigator.userAgentData && navigator.userAgentData.platform) ||
                          navigator.platform || '');
  const IS_WIN = /^win/i.test(PLATFORM);
  const DAEMON_CMD = IS_WIN ? 'py -3.11 daemon/webflow_bridge.py'
                            : 'python3 daemon/webflow_bridge.py';
  const DAEMON_UV_CMD = 'uv run --python 3.11 daemon/webflow_bridge.py';
  const EXT_URL = IS_EDGE ? 'edge://extensions' : 'chrome://extensions';

  const versionEl = document.getElementById('version');
  const mainCard = document.getElementById('mainCard');
  const mainWord = document.getElementById('mainWord');
  const wizardEl = document.getElementById('wizard');
  const wizRowsEl = document.getElementById('wizRows');
  const recheckBtn = document.getElementById('recheckBtn');
  const resultEl = document.getElementById('result');

  let bgAlive = false;
  let daemonConnected = false;
  let state = 'checking';       // 'checking' | 'inactive' | 'active'

  // Static info: extension version (manifest). The version appears exactly
  // once, in the header chip (#version); port / local-daemon rows are gone.
  const extVersion = (chrome.runtime.getManifest() || {}).version || '';
  if (extVersion) versionEl.textContent = 'v' + extVersion;

  // Dot states live on the card: the whole main card is the status display
  // (neutral grey checking / red inactive / green active) and its dot is a
  // single disc inside it, driven purely by the card data-state in popup.css
  // (white on the filled states, pulsing while probing) — no JS dot juggling.
  function setActState(s) {
    state = s;
    mainCard.dataset.state = s;
    mainCard.setAttribute('aria-disabled', (s === 'checking') ? 'true' : 'false');
    mainWord.textContent = (s === 'checking') ? T('checking')
                         : (s === 'active') ? T('active') : T('inactive');
  }

  function showResult(text) {
    resultEl.textContent = text;
    resultEl.classList.add('ok');
    resultEl.classList.remove('hidden');
  }

  function hideResult() {
    resultEl.classList.add('hidden');
  }

  function showWizard() { wizardEl.classList.remove('hidden'); }
  function hideWizard() { wizardEl.classList.add('hidden'); }

  // Wrap chrome.runtime.sendMessage so a missing receiver / thrown error
  // becomes a normal {ok:false, error} reply instead of an exception.
  function send(type, extra) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(Object.assign({ type: type }, extra || {}), (resp) => {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: chrome.runtime.lastError.message });
            return;
          }
          resolve(resp || { ok: false, error: T('no_bg_response') });
        });
      } catch (err) {
        resolve({ ok: false, error: String((err && err.message) || err) });
      }
    });
  }

  function truncate(text, max) {
    const s = String(text);
    return s.length > max ? s.slice(0, max) + '…' : s;
  }

  // ------------------------------------------------------------------
  // Activation checklist (方案A). Rows: Daemon running / Extension ready /
  // Active tab debug-able. A failing row carries its own fix: only static
  // template copy goes through innerHTML; anything dynamic (raw daemon
  // errors) is always rendered via textContent.
  // ------------------------------------------------------------------

  const ROW_NAMES = {
    daemon: T('row_daemon'),
    ext: T('row_ext'),
    page: T('row_page'),
  };

  function rowIcon(rowState) {
    if (rowState === 'ok') {
      return '<svg viewBox="0 0 16 16" width="10" height="10" fill="none" '
           + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
           + 'stroke-linejoin="round" aria-hidden="true">'
           + '<path d="M3.2 8.4l3.2 3.2 6.4-7"/></svg>';
    }
    if (rowState === 'bad') {
      return '<svg viewBox="0 0 16 16" width="10" height="10" fill="none" '
           + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
           + 'aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
    }
    return rowState === 'busy' ? '·' : '…';
  }

  // Fix content builders (only invoked for 'bad' rows).
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
    fix.push({ type: 'text', html: T('ext_fix_1', { ext_url: EXT_URL }) });
    fix.push({ type: 'text', html: T('ext_fix_2') });
    fix.push({ type: 'text', html: T('press_recheck') });
    return fix;
  }

  // Map a real wf-evaluate failure to page-row advice (same classifier the
  // background uses — see background.js error strings, never invented).
  function pageFix(errText) {
    const low = String(errText || '').toLowerCase();
    const fix = [];
    let suppressRaw = false;
    if (/cannot attach debugger to tab|cannot be debugged|must be a debuggable page|no active tab found/.test(low)) {
      fix.push({ type: 'text', html: T('page_fix_switch') });
      fix.push({ type: 'text',
                 html: T(IS_EDGE ? 'page_fix_restricted_edge' : 'page_fix_restricted') });
      suppressRaw = true;
    } else if (/another debugger is already attached|already attached to this tab/.test(low)) {
      fix.push({ type: 'text', html: T('page_fix_devtools') });
    } else {
      fix.push({ type: 'text', html: T('page_fix_generic', { ext_url: EXT_URL }) });
      fix.push({ type: 'text', html: T('press_recheck') });
    }
    if (errText && !suppressRaw) fix.push({ type: 'raw', text: truncate(errText, MAX_RESULT) });
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
    icon.innerHTML = rowIcon(rowState);
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
          el.innerHTML = item.html;            // static template copy only
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
          el.textContent = item.text;          // dynamic error — textContent only
          box.appendChild(el);
        }
      }
      li.appendChild(box);
    }
    wizRowsEl.appendChild(li);
  }

  function clearRows() { wizRowsEl.textContent = ''; }

  function renderRows(rows) {
    clearRows();
    for (const key of ['daemon', 'ext', 'page']) {
      const r = rows[key];
      addRow(ROW_NAMES[key], r.state,
             r.fix || (r.note ? [{ type: 'note', text: r.note }] : null));
    }
  }

  // Clipboard write: navigator.clipboard with an execCommand fallback (the
  // popup click counts as a user gesture in both paths).
  async function copyText(text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (_) { /* fall through to execCommand */ }
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
    const ok = await copyText(btn.dataset.cmd || '');
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

  // Live probe of the background: fills bgAlive / daemonConnected, updates
  // the whole-card status display (red inactive / green active). Never throws.
  async function refreshPing() {
    const resp = await send('wf-ping');
    bgAlive = !!(resp && resp.ok);
    if (!bgAlive) {
      setActState('inactive');
      return { ext: false, daemon: false };
    }
    daemonConnected = resp.daemon === 'connected';
    setActState(daemonConnected ? 'active' : 'inactive');
    return { ext: true, daemon: daemonConnected };
  }

  // One full diagnosis pass for the checklist. `pageErrHint` (optional) is a
  // fresh wf-evaluate error from the Active click — reuse it for the page row
  // instead of probing twice.
  async function diagnose(pageErrHint) {
    showWizard();
    clearRows();
    for (const key of ['daemon', 'ext', 'page']) {
      addRow(ROW_NAMES[key], 'busy', null);
    }

    const st = await refreshPing();

    if (!st.ext) {
      const note = T('note_ext_down');
      renderRows({
        daemon: { state: 'pending', note: note },
        ext: { state: 'bad', fix: extFix() },
        page: { state: 'pending', note: note },
      });
      return;
    }

    if (!st.daemon) {
      renderRows({
        daemon: { state: 'bad', fix: daemonFix() },
        ext: { state: 'ok' },
        page: { state: 'pending', note: T('note_daemon_pending') },
      });
      return;
    }

    // Daemon reachable — the only remaining unknown is the active tab.
    let pageOk = true;
    let pageErr = '';
    if (pageErrHint) {
      pageOk = false;
      pageErr = pageErrHint;
    } else {
      const resp = await send('wf-evaluate', { code: '(() => document.title)()' });
      pageOk = !!(resp && resp.ok);
      pageErr = pageOk ? '' : ((resp && resp.error) || T('unknown_error'));
    }
    renderRows({
      daemon: { state: 'ok' },
      ext: { state: 'ok' },
      page: pageOk ? { state: 'ok' } : { state: 'bad', fix: pageFix(pageErr) },
    });
    if (pageOk) hideWizard();   // all ✓ → the button is Active now
  }

  async function onMainClick() {
    if (state === 'checking') return;
    hideResult();
    hideWizard();
    await refreshPing();        // live re-check — the daemon may have changed
    if (state === 'inactive') { // not active yet → open the activation checklist
      await diagnose();
      return;
    }
    // Active: verify the channel end-to-end with one real evaluate.
    const resp = await send('wf-evaluate', { code: '(() => document.title)()' });
    if (resp && resp.ok) {
      showResult(T('test_ok'));
      return;
    }
    const errText = (resp && resp.error) || T('unknown_error');
    await diagnose(errText);    // the page row explains what to fix
  }

  // Initial load: probe once; the card lands on Active (green) or Inactive (red).
  setActState('checking');
  refreshPing();
  mainCard.addEventListener('click', onMainClick);
  mainCard.addEventListener('keydown', (ev) => {
    // role=button: Enter / Space activate the whole card like a button.
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      onMainClick();
    }
  });
  recheckBtn.addEventListener('click', () => diagnose());
})();
