// Webflow Bridge — background service worker.
//
// Holds one WebSocket to the local web-flow daemon
// (ws://127.0.0.1:10087) and relays commands to Chrome tabs (default: the
// ACTIVE tab):
//   * {id, action:"evaluate", code, tabId?}
//                                   -> chrome.debugger (CDP)
//       Runtime.evaluate on the active tab (see "Why chrome.debugger?"
//       below). An explicit tabId (chrome.tabs.get-resolved) targets that
//       tab instead — ensureDebugger switches the session to it first.
//   * {id, action:"cdp", method, params?, tabId?}
//                                   -> generic chrome.debugger passthrough:
//       ANY DevTools Protocol command (Input.*, Page.*, DOM.*, Network.*,
//       Runtime.*, ...) on the targeted tab (default active). No allowlist —
//       this is a local personal tool; the raw CDP result is the value.
//   * {id, action:"tabs_list"}       -> chrome.tabs.query({}): one
//       {id, url, title, active, windowId, index} per tab (undefined fields
//       omitted; chrome:// pages may expose no url/title).
//   * {id, action:"tabs_close", tabId?}
//                                   -> chrome.tabs.remove(tabId? default active).
//   * {id, action:"tabs_activate", tabId?}
//                                   -> activate + focus tabId? default active.
//   * {id, action:"tabs_open", url}  -> chrome.tabs.create({url}); url must
//       be http(s). Reply value {id, url} of the new tab.
//   * {id, action:"tabs_close_all_but", tabId?}
//                                   -> close every tab in the same window as
//       tabId (default active) except tabId itself; reply value
//       {closed: <count>}. The last-tab case (Chrome closes the window) is
//       still attempted; a failed removal replies {ok:false, error}.
//   * {id, action:"probe", code?}    -> diagnostic: runs the snippet through
//       the injection paths that survive current Chrome (func-based
//       executeScript in ISOLATED/MAIN worlds; MAIN-world new Function;
//       chrome.debugger CDP Runtime.evaluate) and reports the raw per-path
//       results over WS.
//   * {id, action:"navigate", url, tabId?, newTab?, group_title?}
//                                   -> newTab absent/false (default):
//       chrome.tabs.update(tabId?|active, {url}); reply {ok:true} (the
//       pre-Phase-B wire shape, unchanged). newTab:true: chrome.tabs.create
//       ({url, active:true}) and, when group_title is given, chrome.tabs.group
//       + chrome.tabGroups.update(title); reply {success:true, tabId, groupId?}.
//       Never switches the debugger session (CDP sessions survive same-tab
//       navigation; the session only targets the tab it is attached to).
//   * {id, action:"find_tab", url, active?}
//                                   -> find an open tab whose URL matches url
//       (exact, then prefix, then substring; current-window tabs first, then
//       other windows). value {success:true, url, tabId} — or {success:false,
//       error:"no tab matches <url>"}. Never creates tabs; active:true
//       activates the matched tab.
//   * {id, action:"snapshot", max?}
//                                   -> accessibility-like snapshot of the
//       target tab: value {url, title, nodes:[{ref:"@e0", tag, role, name,
//       text, path}, ...]} of visible interactive/informative elements (capped
//       at max, default 400). The emitted list is cached per tab so click/fill
//       can resolve "@eN" refs while the DOM stays unchanged.
//   * {id, action:"click", selector|"@eN", index?}
//                                   -> click an element addressed by a CSS
//       selector or by a snapshot "@eN" ref on the same tab (a stale/missing
//       snapshot is an error). value {success:true, tag, text}.
//   * {id, action:"fill", selector|"@eN", value, mode?}
//                                   -> fill a form control (mode "value":
//       native value setter + input/change events, React/DOM-safe; auto-
//       detected for input/textarea/select) or type into a contenteditable
//       region (mode "contenteditable": focus via evaluate + CDP
//       Input.insertText). value {success:true, tag, mode}.
//   * {id, action:"screenshot", format?, quality?, selector?, fullPage?}
//                                   -> Page.captureScreenshot of the active
//       tab: whole viewport, the full page (fullPage:true), or a clip of the
//       element behind selector (scrolled into view first). value {base64,
//       mime:"image/png"|"image/jpeg", width, height} — the CLIENT writes
//       the file (the extension cannot write arbitrary local paths).
//   * {id, action:"upload", selector|"@eN", file}
//                                   -> DOM.setFileInputFiles puts a LOCAL
//       absolute path onto the matched <input type="file"> (the BROWSER
//       process reads the path — no base64 round-trip). value {success:true,
//       file, tag:"input"}.
//   * {id, action:"handle_file_chooser", file, timeoutMs?}
//                                   -> programmatic answer to an intercepted
//       native file chooser: clicking any file input / custom upload control
//       fires Page.fileChooserOpened (Page.setInterceptFileChooserDialog
//       {enabled:true} runs on every attach) instead of the native dialog;
//       DOM.setFileInputFiles {backendNodeId} then puts a LOCAL absolute
//       path onto that node. value {success:true, file, mode}.
//   * {id, action:"save_as_pdf"}   -> Page.printToPDF {printBackground:true}
//       of the active tab. value {base64, mime:"application/pdf"} — the
//       CLIENT writes the file.
//   * {id, action:"mouse_click", x?, y?, selector?}
//                                   -> Input.dispatchMouseEvent mousePressed
//       + mouseReleased (button "left") at viewport CSS px; a selector is
//       scrolled into view and clicked at its element center. value
//       {success:true, x, y}.
//   * {id, action:"send_key", key, modifiers?, selector?}
//                                   -> focus the selector first when given,
//       then Input.dispatchKeyEvent keyDown + keyUp (Enter/Tab/Escape/.../
//       a-z/0-9) with the CDP modifiers bitmask. value {success:true, key}.
//   * {id, action:"type_text", text, selector?}
//                                   -> focus the selector first when given,
//       then CDP Input.insertText types text at the caret. value
//       {success:true, len}.
// Replies stream back over the same WebSocket as {id, ok, value|error}.
//
// Why chrome.debugger instead of a content script?
//   1. MV3 hardcodes a Content Security Policy into every content-script
//      isolated world whose allowed script-src sources omit eval / string
//      compilation, so direct eval()/new Function() in a content script is
//      blocked regardless of the page CSP or the manifest (empirically
//      verified on x.com, Chrome 152).
//   2. chrome.scripting.executeScript no longer accepts a 'code' string
//      (only 'files'/'func'), and compiling a string in the MAIN world via
//      new Function inside an injected func is blocked by page CSP on strict
//      sites (x.com).
//   3. chrome.debugger Runtime.evaluate is the channel the DevTools console
//      uses: it runs in the page's MAIN world, is immune to page CSP, and
//      returns JSON-safe results with returnByValue:true. Verified working on
//      x.com.
//
// ONE debugger session is attached per active tab and REUSED across evaluate
// calls (no per-call attach/detach flicker during long publish runs). The
// session survives same-tab navigation, so the navigate action does not
// detach. It is cleaned up when the daemon WebSocket closes, when a different
// tab is targeted, or when a command fails because the session died;
// chrome.debugger.onDetach additionally nulls stale state whenever the browser
// ends the session (tab closed, DevTools took over, renderer gone, ...).
//
// Reconnects automatically with exponential backoff capped at 30 s. A
// heartbeat keeps the socket + service worker alive while the daemon is up.
// The popup can explicitly pause the link (wf-disconnect): the socket closes
// and every automatic redial path is skipped until wf-reconnect.
// A chrome.alarms watchdog ('webflow-reconnect', 0.5 min period) is the
// fallback for MV3 worker suspension: timers die with the worker, but the
// alarm still fires on the next wake-up and force-reconnects a dead socket.

const WS_URL = 'ws://127.0.0.1:10087';
const CONFIG_URL = 'http://127.0.0.1:10086/config'; // daemon token bootstrap
const TOKEN_STORE_KEY = 'wbf_token';                  // chrome.storage.local key
const SUSPEND_STORE_KEY = 'wbfSuspended';             // persisted popup Disconnect flag
const CONFIG_FETCH_TIMEOUT_MS = 2500;
const MAX_BACKOFF_MS = 30000;   // reconnect backoff cap (spec)
// wf-dial-now waits at most this long for the local WS handshake before it
// answers the popup. The handshake is loopback-only, so a live daemon opens
// it in a few ms; the cap only bounds the daemon-down failure path.
const DIAL_WAIT_MS = 1500;
const HEARTBEAT_MS = 15000;     // < 30 s MV3 idle limit
const DEBUGGER_VERSION = '1.3'; // chrome.debugger protocol version
// P2: a single chrome.debugger.sendCommand has no reply deadline in the
// protocol, so while the page is blocked on a native dialog / credential
// prompt it never settles. Every call is raced against this cap through
// sendCdp(); it must stay well below the daemon's 120 s round-trip cap.
const CDP_TIMEOUT_MS = 30000;
const COLLECTOR_TIMEOUT_MS = 10000;   // attach-time domain enables (best-effort)
// P1: native-dialog policy. 'auto-accept' (default) resolves every
// Page.javascriptDialogOpening at the browser layer immediately; 'manual'
// leaves it pending for the explicit handle_dialog action. The daemon sends
// set_dialog_policy over the WS to keep this in sync with its own default.
const DIALOG_POLICY_DEFAULT = 'auto-accept';
const IS_EDGE = /Edg\//.test(navigator.userAgent || '');
// The restricted-site names in the attach-failure footnote are runtime-
// specific: Chrome users see chrome:// + the Chrome Web Store, Edge users
// see edge:// + the Edge Add-ons store (mirrors popup.js IS_EDGE).
const RESTRICTED_SUFFIX = IS_EDGE
  ? 'edge:// and Edge Add-ons store pages cannot be debugged'
  : 'chrome:// and Chrome Web Store pages cannot be debugged';

const DEFAULT_PROBE_CODE =
  "(() => ({ url: location.href, title: document.title, probe: 1 + 1 }))()";

let ws = null;
let backoff = 1000;             // 1s -> 2s -> 4s -> ... -> 30s
let reconnectTimer = null;
let connectInFlight = false;    // dedupe concurrent connect() calls (reconnect + dial)
let heartbeatTimer = null;
let suspended = false;          // popup Disconnect: socket + auto-reconnect paused
let suspendStateEpoch = 0;      // bumped on every local suspend/resume decision

// ---------------- persisted pause flag --------------
// The popup's Disconnect must survive MV3 service-worker recycling and full
// browser restarts. The manifest declares the "storage" permission, so
// chrome.storage.local is the primary mechanism. IndexedDB is kept as a
// fallback — it needs no permission and lives in the same profile, so it
// still works if the permission ever goes missing. Both reads/writes are
// wrapped so a failure is a conservative no-op (read -> connect as usual,
// write -> the live in-memory disconnect still stands).
const SUSPEND_DB_NAME = 'wbf_state';
const SUSPEND_DB_STORE = 'kv';
const SUSPEND_DB_KEY = SUSPEND_STORE_KEY;

function hasChromeStorage() {
  try {
    return typeof chrome !== 'undefined' && !!chrome.storage && !!chrome.storage.local &&
           typeof chrome.storage.local.get === 'function' &&
           typeof chrome.storage.local.set === 'function';
  } catch (_) { return false; }
}

function idbOpen() {
  return new Promise((resolve, reject) => {
    let req;
    try { req = indexedDB.open(SUSPEND_DB_NAME, 1); }
    catch (e) { reject(e); return; }
    req.onupgradeneeded = () => {
      try {
        if (!req.result.objectStoreNames.contains(SUSPEND_DB_STORE)) {
          req.result.createObjectStore(SUSPEND_DB_STORE);
        }
      } catch (_) { /* store already there */ }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error('idb open failed'));
  });
}

async function idbGet(key) {
  const db = await idbOpen();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(SUSPEND_DB_STORE, 'readonly');
      const rq = tx.objectStore(SUSPEND_DB_STORE).get(key);
      rq.onsuccess = () => resolve(rq.result);
      rq.onerror = () => reject(rq.error || new Error('idb get failed'));
    });
  } finally { db.close(); }
}

async function idbSet(key, value) {
  const db = await idbOpen();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(SUSPEND_DB_STORE, 'readwrite');
      tx.objectStore(SUSPEND_DB_STORE).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error || new Error('idb set failed'));
      tx.onabort = () => reject(tx.error || new Error('idb set aborted'));
    });
  } finally { db.close(); }
}

async function readPersistedSuspended() {
  if (hasChromeStorage()) {
    try {
      const stored = await chrome.storage.local.get(SUSPEND_STORE_KEY);
      return !!(stored && stored[SUSPEND_STORE_KEY] === true);
    } catch (_) {
      return false;             // storage unreadable: fall back to connecting
    }
  }
  try {
    return (await idbGet(SUSPEND_DB_KEY)) === true;
  } catch (_) {
    return false;               // fallback unreadable: fall back to connecting
  }
}

async function persistSuspended(value) {
  if (hasChromeStorage()) {
    try { await chrome.storage.local.set({ [SUSPEND_STORE_KEY]: value }); }
    catch (_) { /* write failed: local flag and this disconnect still stand */ }
    return;
  }
  try { await idbSet(SUSPEND_DB_KEY, value); }
  catch (_) { /* write failed: local flag and this disconnect still stand */ }
}

// Memoized: resolves once the persisted pause flag has been read. Every dial
// path (connect / scheduleReconnect / the alarm watchdog / wf-ping) awaits it
// BEFORE deciding, which closes the cold-start race where `suspended` is
// still at its default and a dial could sneak out before the value is known.
const suspendStateReady = (async () => {
  const epochAtStart = suspendStateEpoch;
  const loaded = await readPersistedSuspended();
  // A suspend/resume that happened while the read was in flight is newer and
  // must win over the stale persisted value.
  if (suspendStateEpoch === epochAtStart) suspended = loaded;
  return suspended;
})();

// ---------------- debugger session state ----------------

let debuggerTabId = null;       // tab the ACTIVE command session targets
// Every tab we currently hold a chrome.debugger session on. Normally this is
// just {debuggerTabId}; a tab with a PENDING native dialog is kept attached
// ("pinned") even when commands move to another tab, because detaching the tab
// that owns a dialog makes that dialog unresolvable: Chrome forgets it and
// Page.handleJavaScriptDialog then answers "No dialog is showing". The pin is
// released when the dialog is resolved or closed.
const attachedTabs = new Set();

// P1: current native-dialog policy ('auto-accept' | 'manual'). Read by the
// Page.javascriptDialogOpening listener; updated by the set_dialog_policy
// action / control message. Default matches the daemon's default.
let dialogPolicy = DIALOG_POLICY_DEFAULT;
// P5: top-frame URL of the current session when it is a browser error page
// (chrome-error://chromewebdata/ — network failure, certificate interstitial,
// cancelled auth). Set from Page.frameNavigated and from a Page.getFrameTree
// probe on attach, reset on every (re)attach; lets evaluate report a clear
// reason instead of returning meaningless values off an error page.
let errorPage = null;
// P1: last automatic dialog-accept failure ({type,message,error,at}) or null.
// Exposed through probe (dialog.lastError) and mirrored to the daemon as an
// unsolicited notice (GET /status last_notice + next /command response).
let lastDialogAutoError = null;
// P5: native-download + control-handoff feedback. `downloadRecords` is a
// bounded newest-last ring served by list_downloads / probe; `lastDownload`
// is the newest entry. A popup opened by the controlled tab pushes a notice.
let downloadRecords = [];
let lastDownload = null;
let lastPopupNoticeAt = 0;

// The browser ends our session on its own (tab closed, navigated somewhere
// non-debuggable, DevTools took over, renderer gone, ...). Null the state so
// the next evaluate attaches a fresh session instead of reusing a dead one.
chrome.debugger.onDetach.addListener((source, reason) => {
  if (!source || typeof source.tabId !== 'number') return;
  if (source.tabId === debuggerTabId) {
    console.warn('[web-flow] debugger session ended on tab',
                 source.tabId, 'reason:', reason);
    debuggerTabId = null;
    pendingFileChooser = null;
  }
  attachedTabs.delete(source.tabId);
  // A pinned dialog tab that detaches on its own (tab closed, renderer gone,
  // DevTools took over) loses the only handle that could resolve its dialog;
  // drop the now-unresolvable pending state instead of fast-failing forever.
  if (pendingDialog && pendingDialog.tabId === source.tabId) {
    pendingDialog = null;
    if (lastDialogAutoError && lastDialogAutoError.tabId === source.tabId) {
      lastDialogAutoError = null;
    }
  }
});

// P5: a page that opens a popup (target=_blank / window.open) makes the new
// tab ACTIVE, so the next active-tab action silently targets the new page
// and the original chain breaks. Detect a tab opened by the controlled tab
// and tell the daemon (additive notice), while tabs_list still lists every
// tab exactly as before.
chrome.tabs.onCreated.addListener((tab) => {
  try {
    if (!tab || tab.openerTabId == null) return;
    if (tab.openerTabId !== debuggerTabId) return;
    const now = Date.now();
    if (now - lastPopupNoticeAt < 1500) return;   // collapse duplicate events
    lastPopupNoticeAt = now;
    const url = tab.url || tab.pendingUrl || 'about:blank';
    notifyDaemon({
      kind: 'control_moved',
      text: 'the controlled page opened a new tab and focus moved to it ' +
            '(tabId ' + tab.id + ': ' + url + '); target it explicitly with ' +
            'tabId if the original page was intended',
      tabId: tab.id,
      url,
    });
  } catch (_) { /* a diagnostic notice must never break the listener */ }
});

// ---------------- humanize (P1, opt-in pacing) ----------------
// Off by default: every path checks `msg.humanize === true`, so the original
// verified flows run byte-for-byte unchanged. Boundaries (red lines): NO
// captcha solving, NO fingerprint/UA spoofing — only timing/rhythm on the
// real input paths (Input.dispatch*, native value setter, el.click).

function humanizeDelay(minMs, maxMs) {
  const span = Math.max(0, maxMs - minMs);
  return new Promise((resolve) =>
    setTimeout(resolve, minMs + Math.floor(Math.random() * (span + 1))));
}

// Optional micro scroll (±10 px each axis) before an evaluate reply is sent;
// runs page-side through the SAME debugger session (no content script).
function humanizeScrollExpression() {
  const dx = Math.floor(Math.random() * 21) - 10;
  const dy = Math.floor(Math.random() * 21) - 10;
  return `(() => { try { window.scrollBy(${dx}, ${dy}); return true; } catch (_) { return false; } })()`;
}

// ---------------- socket management ----------------

// ---------------- daemon auth token (P0-6) ----------------
// The daemon now requires the shared bearer token on the WS handshake
// (ws://127.0.0.1:10087?token=<tok>). We cache it in chrome.storage.local
// ('wbf_token') and bootstrap it from GET http://127.0.0.1:10086/config when
// absent. /config answers no CORS headers, so only an extension page with the
// <all_urls> host permission can read it — a hostile web page cannot.

let wbfToken = null;            // in-memory cache of the daemon auth token
let wbfTokenLegacy = false;     // /config answered 405: pre-auth daemon
let wsEverOpened = false;       // current socket completed a real handshake

// GET /config -> {token} (daemon up) | {legacy:true} (daemon too old, no auth)
// | null (daemon unreachable / timeout — caller retries silently).
function fetchDaemonToken() {
  return new Promise((resolve) => {
    let ctl = null;
    let timer = null;
    try { ctl = new AbortController(); } catch (_) { /* noop */ }
    if (ctl) timer = setTimeout(() => ctl.abort(), CONFIG_FETCH_TIMEOUT_MS);
    const opts = ctl ? { signal: ctl.signal } : {};
    fetch(CONFIG_URL, opts)
      .then((resp) => {
        if (resp.status === 405) return { legacy: true };  // old daemon
        if (!resp.ok) return null;
        return resp.json().then((j) =>
          (j && typeof j.token === 'string') ? { token: j.token } : null);
      })
      .catch(() => null)
      .then((out) => {
        if (timer) clearTimeout(timer);
        resolve(out);
      });
  });
}

// Token to present on the WS handshake, or null when the daemon is
// unreachable (the existing reconnect loop retries, silent while it is down).
async function ensureWsToken() {
  if (wbfToken !== null) return wbfToken;
  if (wbfTokenLegacy) return null;
  try {
    const stored = await chrome.storage.local.get(TOKEN_STORE_KEY);
    if (typeof stored[TOKEN_STORE_KEY] === 'string') {
      wbfToken = stored[TOKEN_STORE_KEY];
      return wbfToken;
    }
  } catch (_) { /* storage unreadable — refetch below */ }
  const out = await fetchDaemonToken();
  if (out === null) return null;                 // daemon down: silent retry
  if (out.legacy) { wbfTokenLegacy = true; return null; }
  wbfToken = out.token;
  try { chrome.storage.local.set({ [TOKEN_STORE_KEY]: wbfToken }); }
  catch (_) { /* keep the in-memory cache */ }
  return wbfToken;
}

// A connection that closed before the handshake completed means the daemon
// rejected us (403: token rotated after a daemon restart) or is down. Drop the
// cached token either way so the next connect refetches /config exactly once
// before retrying — the daemon restart case then heals automatically.
function invalidateWsToken() {
  wbfToken = null;
  try { chrome.storage.local.remove(TOKEN_STORE_KEY); } catch (_) { /* noop */ }
}

async function connect() {
  if (connectInFlight) return;               // one dial at a time (reconnect + wf-dial-now race)
  connectInFlight = true;
  try {
    await suspendStateReady;                 // never dial before the pause flag is known
    if (suspended) return;                   // user paused the link
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    const token = await ensureWsToken();
    if (suspended) return;                   // paused while the token was fetched
    if (token === null && !wbfTokenLegacy) {
      // Daemon not up yet: keep the existing silent backoff loop.
      ws = null;
      scheduleReconnect();
      return;
    }
    const url = wbfTokenLegacy
      ? WS_URL
      : WS_URL + '?token=' + encodeURIComponent(token);
    wsEverOpened = false;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      scheduleReconnect();
      return;
    }
    ws.onopen = () => {
      backoff = 1000;
      wsEverOpened = true;
      startHeartbeat();
      console.log('[web-flow] connected to daemon', url);
    };
    ws.onmessage = (ev) => { handleMessage(ev); };
    ws.onclose = () => {
      console.warn('[web-flow] daemon connection closed; retrying');
      stopHeartbeat();
      if (!wsEverOpened) invalidateWsToken();  // 403 / refused: token may be stale
      ws = null;
      scheduleReconnect();
      cleanupDebuggerSession();   // nothing to serve while the daemon is gone
    };
    ws.onerror = () => {                       // onerror is followed by onclose
      try { ws.close(); } catch (_) { /* noop */ }
    };
  } finally {
    connectInFlight = false;
  }
}

// Resolve true as soon as the current socket reaches OPEN, false after `ms`.
function waitForWsOpen(ms) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    (function tick() {
      if (ws && ws.readyState === WebSocket.OPEN) { resolve(true); return; }
      if (Date.now() - t0 >= ms) { resolve(false); return; }
      setTimeout(tick, 50);
    })();
  });
}

// Popup click on an Inactive card: drop any pending backoff and dial NOW.
// Returns
//   {ok:true,  state:'connected'}
// | {ok:false, state:'suspended'|'disconnected', reason}
// reason distinguishes an unreachable daemon ('daemon_down': no /config on
// :10086, no :10087 listener) from a live daemon whose handshake we could not
// complete ('daemon_busy': stale token / slot held by another browser).
async function dialNow() {
  await suspendStateReady;
  if (suspended) return { ok: false, state: 'suspended', reason: 'suspended' };
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  backoff = 1000;
  if (!ws || (ws.readyState !== WebSocket.OPEN && ws.readyState !== WebSocket.CONNECTING)) {
    connect();                                 // fire-and-wait; connect() dedupes
  }
  if (await waitForWsOpen(DIAL_WAIT_MS)) return { ok: true, state: 'connected' };
  // Not open: a reachable /config means the daemon is up, so the failed dial
  // is a handshake/slot problem rather than a missing daemon.
  const token = await fetchDaemonToken();
  if (ws && ws.readyState === WebSocket.OPEN) return { ok: true, state: 'connected' };
  return {
    ok: false,
    state: 'disconnected',
    reason: token === null ? 'daemon_down' : 'daemon_busy',
  };
}

async function scheduleReconnect() {
  await suspendStateReady;                   // persisted pause flag before deciding
  if (suspended) return;                     // paused: no automatic redial
  if (reconnectTimer) return;                // only one pending timer
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, backoff);
  backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  } else {
    console.warn('[web-flow] daemon not connected; dropped reply', obj);
  }
}

// P1/P5: unsolicited feedback that has no request id of its own (an auto
// dialog-accept failure, a download started, control handed to a new tab).
// Sent as a {"type":"notice"} frame; the daemon records it and surfaces it on
// GET /status and on the next POST /command response.
function notifyDaemon(fields) {
  const payload = Object.assign({ type: 'notice', at: Date.now() }, fields || {});
  if (ws && ws.readyState === WebSocket.OPEN) {
    try { ws.send(JSON.stringify(payload)); } catch (_) { /* best-effort */ }
  }
}

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping' }));
    }
  }, HEARTBEAT_MS);
}

function stopHeartbeat() {
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
}

// ---------------- user-paused link (popup Disconnect / Reconnect) ----------------
// Disconnect is an explicit user action: close the socket and silence every
// automatic redial path (retry timer, heartbeat, alarms watchdog) so the
// daemon cannot be dialed back until the user asks for it. The flag is now
// persisted (chrome.storage.local when the permission exists, IndexedDB
// otherwise) so it also survives a service-worker recycle / browser restart;
// Reconnect clears it and dials immediately. While not suspended, every
// existing connect / reconnect / heartbeat / evaluate path behaves exactly as
// before.
async function suspendConnection() {
  suspended = true;
  suspendStateEpoch += 1;     // beat any in-flight startup read
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  stopHeartbeat();
  const sock = ws;
  ws = null;
  if (sock) {
    // Detach the handlers first: onclose would otherwise scheduleReconnect.
    try {
      sock.onopen = null;
      sock.onmessage = null;
      sock.onerror = null;
      sock.onclose = null;
    } catch (_) { /* noop */ }
    try { sock.close(); } catch (_) { /* noop */ }
  }
  backoff = 1000;
  cleanupDebuggerSession();   // nothing to serve while the link is paused
  // Durable before the popup's reply resolves; a storage write failure is
  // swallowed and the live disconnect above still stands.
  await persistSuspended(true);
}

async function resumeConnection() {
  suspended = false;
  suspendStateEpoch += 1;     // beat any in-flight startup read
  backoff = 1000;
  await persistSuspended(false);
  connect();                  // immediate redial (connect clears any timer)
}

// ---------------- chrome.debugger session manager ----------------

// Detach whatever session we hold (used when targeting a different tab or
// shutting down). Swallows errors: detaching an already-dead session is fine.
async function detachDebugger(tabId) {
  attachedTabs.delete(tabId);
  try { await chrome.debugger.detach({ tabId }); } catch (_) { /* noop */ }
  if (debuggerTabId === tabId) debuggerTabId = null;
}

function cleanupDebuggerSession() {
  const tids = [];
  for (const tid of attachedTabs) tids.push(tid);
  attachedTabs.clear();
  if (debuggerTabId != null && tids.indexOf(debuggerTabId) === -1) {
    tids.push(debuggerTabId);
  }
  debuggerTabId = null;
  for (const tid of tids) {
    chrome.debugger.detach({ tabId: tid }).catch(() => { /* noop */ });
  }
}

// P2: reset the managed session when a command timed out — a CDP call that
// never settled means the session can no longer be trusted (blocked page or
// dead target). Same recovery the transport-rejection paths use: null the
// in-memory state so the next command attaches a fresh session, and detach
// best-effort so the browser-side session does not linger.
//
// P1/P2 (batch 2): if a native dialog is pending, the session is the ONLY
// handle that can resolve it — detaching would also clear pendingDialog via
// onDetach and leave the page blocked with no way out. So keep the session and
// let handle_dialog do its job (a later successful command can still reset).
function resetDebuggerSessionIfCurrent(tabId) {
  if (debuggerTabId !== tabId) return;
  // Only THIS tab's dialog protects its session: another tab's dialog must not
  // keep a dead session alive here.
  if (pendingDialog && pendingDialog.tabId === tabId) return;
  attachedTabs.delete(tabId);
  debuggerTabId = null;
  chrome.debugger.detach({ tabId }).catch(() => { /* noop */ });
}

// P1 (batch 2): a native dialog that is ALREADY known to block the target
// can be reported without touching the browser. The session is deliberately
// left attached so a follow-up handle_dialog can still resolve the dialog —
// the old 30 s timeout detached here and that is what raced handle_dialog.
// Returns an Error or null.
function dialogBlockingError(message) {
  const err = new Error(message);
  // Callers that normally reset the session on any sendCdp failure (a
  // transport error means the session is dead) must NOT reset here: this is a
  // deliberate fast-fail and the session is alive so handle_dialog can use it.
  err.dialogBlocking = true;
  return err;
}

function nativeDialogBlockError(tabId) {
  // Scoped strictly to the requested tab: A's pending dialog must never
  // fast-fail a command, mark a probe path skipped, or appear `blocking` on B.
  // Also independent of which session is currently attached, so targeting the
  // dialog tab again fast-fails in ms even after a detour to another tab.
  if (!pendingDialog || pendingDialog.tabId !== tabId) return null;
  if (dialogPolicy === 'manual') {
    return dialogBlockingError(nativeDialogMessage(pendingDialog, null));
  }
  if (lastDialogAutoError && lastDialogAutoError.tabId === tabId) {
    return dialogBlockingError(
      nativeDialogMessage(pendingDialog, lastDialogAutoError));
  }
  return null;   // auto-accept still in flight: let the command complete
}

function nativeDialogMessage(dialog, autoError) {
  const type = (dialog && dialog.type) ? dialog.type : 'unknown';
  const message = (dialog && dialog.message) ? dialog.message : '';
  const url = (dialog && dialog.url) ? dialog.url : '';
  let text = 'a native ' + type + " dialog is blocking this tab ('" +
             message + "')";
  if (url) text += ' from ' + url;
  if (autoError) {
    text += '; the automatic accept failed (' +
            String((autoError && autoError.error) || autoError) + ')';
  }
  return text + ': call handle_dialog (accept=true) or switch the policy to ' +
         'auto-accept';
}

// P1 (batch 2): commands in flight when a dialog starts blocking the page are
// woken here, so the action that triggered the dialog fails INSIDE that same
// action instead of waiting out CDP_TIMEOUT_MS.
let dialogBlockWaiters = [];
function onDialogBlocked(fn) {
  dialogBlockWaiters.push(fn);
  return () => {
    const i = dialogBlockWaiters.indexOf(fn);
    if (i >= 0) dialogBlockWaiters.splice(i, 1);
  };
}
function notifyDialogBlocked() {
  if (!dialogBlockWaiters.length) return;
  const waiters = dialogBlockWaiters;
  dialogBlockWaiters = [];
  for (const fn of waiters) { try { fn(); } catch (_) { /* noop */ } }
}

// P1/P3 (batch 2): the last CDP command that timed out on the current session
// — a fast-fail hint for `probe` even when no dialog event was seen (e.g. the
// dialog predated attach). Cleared by the next successful command.
let debuggerBlocked = null;   // {method, at, error, tabId} | null

const DIALOG_CONTROL_METHOD = 'Page.handleJavaScriptDialog';

// A "not attached" / "detached" style transport error means the browser-side
// session died under us (a timed-out command resets it, and the reset detaches
// asynchronously) even though the in-memory state can still look live.
function isDetachedError(err) {
  return /not attached|is not attached|detached|No session with given id/i
    .test(String((err && err.message) || err));
}

// P2: the ONLY place chrome.debugger.sendCommand is called. Races the command
// against `timeoutMs` (default CDP_TIMEOUT_MS). On expiry it resets the
// session and rejects with a self-explaining error, so a blocked page fails
// in seconds instead of silently stalling until the daemon's 120 s cap.
//
// opts (optional):
//   noGuard  true -> do not fast-fail / abort on a pending native dialog
//                     (Page.handleJavaScriptDialog and the attach-time domain
//                     enables must run while the page is blocked)
//   noReset  true -> on timeout keep the attached session (best-effort setup)
//   noRetry  true -> disable the detached-error re-attach retry (attach phase)
function sendCdp(tabId, method, params, timeoutMs, opts) {
  const o = opts || {};
  return sendCdpAttempt(tabId, method, params, timeoutMs, o).catch((err) => {
    if (o.noRetry || o._retried || !isDetachedError(err)) throw err;
    // The session died between our last good command and this one. Drop the
    // stale state, re-attach once, and resend exactly once. Safe: a "not
    // attached" rejection means the command never ran.
    attachedTabs.delete(tabId);
    if (debuggerTabId === tabId) debuggerTabId = null;
    return ensureDebugger(tabId).then((attachErr) => {
      if (attachErr) throw new Error(attachErr);
      return sendCdpAttempt(tabId, method, params, timeoutMs,
                            Object.assign({}, o, { _retried: true }));
    });
  });
}

function sendCdpAttempt(tabId, method, params, timeoutMs, o) {
  const limit = (Number.isFinite(timeoutMs) && timeoutMs > 0)
    ? timeoutMs : CDP_TIMEOUT_MS;
  const guard = o.noGuard !== true && method !== DIALOG_CONTROL_METHOD;
  return new Promise((resolve, reject) => {
    let settled = false;
    let unsub = null;
    let timer = null;
    const finish = () => {
      settled = true;
      if (timer) clearTimeout(timer);
      if (unsub) unsub();
    };
    if (guard) {
      const known = nativeDialogBlockError(tabId);
      if (known) { reject(known); return; }
    }
    timer = setTimeout(() => {
      if (settled) return;
      finish();
      const secs = Math.round(limit / 1000);
      const msg = 'CDP ' + method + ' did not respond within ' + secs + 's';
      debuggerBlocked = { method, at: Date.now(), error: msg, tabId };
      if (o.noReset === true) {
        reject(new Error(msg + ' (best-effort setup step skipped)'));
        return;
      }
      resetDebuggerSessionIfCurrent(tabId);
      reject(new Error(
        msg + ': the page may be blocked by a native dialog or credential ' +
        'prompt (try handle_dialog), or the debugger session is dead ' +
        '(retrying re-attaches)'));
    }, limit);
    let call;
    try {
      call = chrome.debugger.sendCommand({ tabId }, method, params || {});
    } catch (err) {
      finish();
      reject(err);
      return;
    }
    if (guard) {
      // Only a dialog on THIS tab may abort this command; a dialog that opened
      // on another tab must not wake/cancel us (cross-tab scope). If the wake
      // is for another tab, re-register so a later dialog on OUR tab still
      // aborts us inside the same action.
      const wake = () => {
        if (settled) return;
        if (!pendingDialog || pendingDialog.tabId !== tabId) {
          unsub = onDialogBlocked(wake);
          return;
        }
        const e = nativeDialogBlockError(tabId) ||
          dialogBlockingError('a native dialog is blocking this tab');
        finish();
        reject(e);
      };
      unsub = onDialogBlocked(wake);
    }
    call.then(
      (res) => {
        if (settled) return;
        finish();
        // Only a real page command clears the "recently blocked" hint: an
        // attach-time setup step (noReset) can answer even while the page
        // itself is frozen, and must not mask the block for probe/handle.
        if (o.noReset !== true) debuggerBlocked = null;
        resolve(res);
      },
      (err) => {
        if (settled) return;
        finish();
        reject(err);
      },
    );
  });
}

// Serialize attach/detach transitions so interleaved requests (the daemon may
// hold several HTTP requests in flight) cannot corrupt the session state.
let debuggerOpChain = Promise.resolve();

function ensureDebugger(tabId) {
  const run = debuggerOpChain.then(() => ensureDebuggerLocked(tabId));
  debuggerOpChain = run.then(() => undefined, () => undefined);
  return run;
}

async function ensureDebuggerLocked(tabId) {
  if (debuggerTabId === tabId) return null;   // live session; onDetach nulls it if it dies
  // A tab that owns a pending native dialog stays attached ("pinned") across a
  // switch to another tab; detaching it would make its dialog unresolvable.
  const pinnedDialogTab = (pendingDialog && typeof pendingDialog.tabId === 'number')
    ? pendingDialog.tabId : null;
  if (debuggerTabId != null && debuggerTabId !== pinnedDialogTab) {
    await detachDebugger(debuggerTabId);      // switch to the newly targeted tab
  }
  if (attachedTabs.has(tabId)) {
    // Reuse a still-attached session (e.g. returning to the pinned dialog tab)
    // instead of detaching/re-attaching it — a re-attach loses the dialog.
    debuggerTabId = tabId;
    return null;
  }
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await chrome.debugger.attach({ tabId }, DEBUGGER_VERSION);
      attachedTabs.add(tabId);
      debuggerTabId = tabId;
      try { await enableCollectorDomains(tabId); } catch (_) { /* best-effort */ }
      return null;
    } catch (err) {
      const text = String((err && err.message) || err);
      const busy = /another debugger|already attached/i.test(text);
      if (busy && attempt === 0) {
        // Could be a stale session WE own from a previous service-worker
        // instance (debugger sessions survive MV3 worker restarts while our
        // in-memory debuggerTabId does not). detach() only succeeds when the
        // session is ours; DevTools-owned sessions reject here, and the next
        // attempt then reports busy.
        try { await chrome.debugger.detach({ tabId }); } catch (_) { /* not ours */ }
        continue;
      }
      if (busy) {
        return 'another debugger is already attached to this tab: ' + text +
               ' — close DevTools (F12) on that tab and retry';
      }
      return 'cannot attach debugger to tab ' + tabId + ': ' + text +
             ' (the active tab must be a debuggable page — open a normal ' +
             'http(s) site; ' + RESTRICTED_SUFFIX + ')';
    }
  }
  return 'cannot attach debugger to tab ' + tabId;
}

// ---------------- CDP event collectors (network / console) ----------------
// The single debugger session (one attached tab at a time) also feeds two
// bounded ring buffers of CDP events. list_network_requests /
// get_network_request / list_console_messages read them. Buffers are reset
// on every (re)attach so their contents always describe the current session
// from its attach point onward. Domains are enabled best-effort: if an
// enable fails the session still works, the collectors just stay empty.

const EVENT_CAP = 300;
let netEvents = [];        // [{requestId,url,method,type,status,mimeType,size,timestamp}]
let consoleEvents = [];    // [{type,text,timestamp}]
// v1.4 wait_for(networkIdleMs): wall-clock ms of the last request/response
// event for the current debugger session. Reset on every (re)attach so it
// only ever describes events we could have observed.
let lastNetActivity = 0;

// JS-dialog state machine (Page domain). Chrome auto-dismisses dialogs while
// a debugger is attached UNLESS something listens for the opening event and
// resolves them via Page.handleJavaScriptDialog. We keep the latest opening
// here so the handle_dialog action can accept/dismiss/answer it. While an
// entry is pending the page script is blocked on the dialog, so handle_dialog
// must always resolve it (see handleDialog) or the tab hangs.
// Always carries the owning `tabId`: a "this tab is blocked" decision must be
// scoped to one tab, so A's dialog can never affect B (nativeDialogBlockError).
let pendingDialog = null;  // {tabId,type,message,defaultPrompt,url,hasBrowserHandler,openedAt} | null

// File-chooser interception (Page domain). enableCollectorDomains turns on
// Page.setInterceptFileChooserDialog after every attach, so a file input /
// custom upload control that would normally pop the NATIVE "open file"
// dialog instead surfaces as a Page.fileChooserOpened event with the input's
// backendNodeId — and handle_file_chooser resolves it programmatically via
// DOM.setFileInputFiles {backendNodeId} (no native UI). Newest opening wins.
let pendingFileChooser = null;  // {backendNodeId, frameId, mode, openedAt} | null

function ringPush(arr, item) {
  arr.push(item);
  if (arr.length > EVENT_CAP) arr.splice(0, arr.length - EVENT_CAP);
}

async function enableCollectorDomains(tabId) {
  netEvents = [];
  consoleEvents = [];
  lastNetActivity = Date.now();
  errorPage = null;
  // Page.enable makes JS dialogs (alert/confirm/prompt/beforeunload) surface
  // as Page.javascriptDialogOpening events instead of Chrome auto-dismissing
  // them while a debugger is attached (see handleDialog below).
  //
  // P2/P3 (batch 2): these are best-effort setup steps. They are issued in
  // PARALLEL under one budget and MUST NOT reset the freshly attached session
  // on timeout (noReset) — on a page blocked by a dialog they cannot answer,
  // and the old per-step reset tore down the session before handle_dialog
  // could use it (the P2 race). Backoff: no guard/no retry either.
  const setup = (method, p) => sendCdp(tabId, method, p, COLLECTOR_TIMEOUT_MS,
    { noGuard: true, noReset: true, noRetry: true });
  const results = await Promise.allSettled([
    setup('Network.enable', undefined),
    setup('Runtime.enable', undefined),
    setup('Page.enable', undefined),
    // Intercept native file-chooser dialogs: any file input (or custom upload
    // control that opens one) then fires Page.fileChooserOpened instead of
    // showing the OS dialog (see handleFileChooser). Idempotent.
    setup('Page.setInterceptFileChooserDialog', { enabled: true }),
    // P5: keep the browser's normal download behaviour (do NOT redirect the
    // destination) but ask for download events so an attachment navigation can
    // be reported instead of silently doing nothing.
    setup('Page.setDownloadBehavior', { behavior: 'default', eventsEnabled: true }),
    setup('Browser.setDownloadBehavior', { behavior: 'default', eventsEnabled: true }),
    // P5: the tab may already be sitting on a browser error page when we
    // attach, so read the committed top frame once here; Page.frameNavigated
    // keeps it current afterwards.
    setup('Page.getFrameTree', {}),
  ]);
  const treeResult = results[6];
  if (treeResult && treeResult.status === 'fulfilled') {
    try {
      const frame = (treeResult.value && treeResult.value.frameTree &&
                     treeResult.value.frameTree.frame) || {};
      if (/^chrome-error:\/\//i.test(String(frame.url || ''))) {
        errorPage = {
          url: String(frame.url || ''),
          unreachableUrl: String(frame.unreachableUrl || ''),
          at: Date.now(),
        };
      }
    } catch (_) { /* best-effort */ }
  }
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (!source || !attachedTabs.has(source.tabId)) return;  // only our sessions
  if (!params || typeof params !== 'object') return;
  // Dialog lifecycle events are honoured for EVERY attached tab (a pinned
  // dialog tab keeps reporting its own dialog); every other event describes
  // only the active command session, so per-tab counters stay tab-scoped.
  if (method !== 'Page.javascriptDialogOpening' &&
      method !== 'Page.javascriptDialogClosed' &&
      source.tabId !== debuggerTabId) return;
  try {
    if (method === 'Network.requestWillBeSent') {
      const req = params.request || {};
      const url = typeof req.url === 'string' ? req.url : '';
      if (!/^https?:/i.test(url)) return;   // skip chrome-extension:// data: noise
      lastNetActivity = Date.now();
      ringPush(netEvents, {
        requestId: String(params.requestId || ''),
        url,
        method: typeof req.method === 'string' ? req.method : '',
        type: typeof params.type === 'string' ? params.type : '',
        status: null,
        mimeType: null,
        size: null,
        timestamp: Date.now(),
      });
    } else if (method === 'Network.responseReceived') {
      lastNetActivity = Date.now();
      const rec = netEvents.find((e) => e.requestId === String(params.requestId));
      if (!rec) return;
      const resp = params.response || {};
      rec.status = typeof resp.status === 'number' ? resp.status : null;
      rec.mimeType = typeof resp.mimeType === 'string' ? resp.mimeType : null;
    } else if (method === 'Network.loadingFinished') {
      const rec = netEvents.find((e) => e.requestId === String(params.requestId));
      if (!rec) return;
      rec.size = (typeof params.encodedDataLength === 'number')
        ? params.encodedDataLength : null;
    } else if (method === 'Runtime.consoleAPICalled') {
      const parts = (params.args || []).map((a) => {
        if (!a) return '';
        if (a.value !== undefined) {
          return (typeof a.value === 'string') ? a.value : JSON.stringify(a.value);
        }
        return (typeof a.description === 'string') ? a.description : '';
      });
      ringPush(consoleEvents, {
        type: String(params.type || 'log'),
        text: parts.join(' ').slice(0, 2000),
        timestamp: Date.now(),
      });
    } else if (method === 'Runtime.exceptionThrown') {
      const d = params.exceptionDetails || {};
      let text = d.text || 'Uncaught';
      if (d.exception && typeof d.exception.description === 'string') {
        text += ': ' + d.exception.description;
      }
      ringPush(consoleEvents, {
        type: 'exception',
        text: String(text).slice(0, 500),
        timestamp: Date.now(),
      });
    } else if (method === 'Page.javascriptDialogOpening') {
      // The page is now blocked on the dialog until we resolve it via
      // Page.handleJavaScriptDialog (see handleDialog). Keep the newest
      // opening, tagged with its tab; one dialog per tab, but different tabs
      // can each hold one.
      const previous = pendingDialog;
      pendingDialog = {
        tabId: source.tabId,
        type: String(params.type || 'alert'),
        message: typeof params.message === 'string' ? params.message : '',
        defaultPrompt: typeof params.defaultPrompt === 'string' ? params.defaultPrompt : '',
        url: typeof params.url === 'string' ? params.url : '',
        hasBrowserHandler: !!params.hasBrowserHandler,
        openedAt: Date.now(),
      };
      // This opening replaces any previous tab's entry: release that tab's
      // pinned session (if any) so it is not left attached for no reason.
      if (previous && previous.tabId !== source.tabId &&
          previous.tabId !== debuggerTabId && attachedTabs.has(previous.tabId)) {
        detachDebugger(previous.tabId);
      }
      // P1 (batch 2): in 'manual' mode wake any in-flight guarded command
      // immediately — the action that triggered the dialog fails in the same
      // action instead of waiting out the 30 s CDP cap (per-tab, see waiter).
      if (dialogPolicy === 'manual') notifyDialogBlocked();
      // P1: default policy resolves the dialog at the browser layer right
      // now (fire-and-forget); 'manual' leaves it for handle_dialog.
      autoHandleDialog(source.tabId, pendingDialog);
    } else if (method === 'Page.javascriptDialogClosed') {
      if (pendingDialog && pendingDialog.tabId === source.tabId) {
        pendingDialog = null;
        if (lastDialogAutoError && lastDialogAutoError.tabId === source.tabId) {
          lastDialogAutoError = null;
        }
      }
      // The dialog is gone: if we were pinning this tab while another session
      // is active, release it so it is not left attached for no reason.
      if (source.tabId !== debuggerTabId && attachedTabs.has(source.tabId)) {
        detachDebugger(source.tabId);
      }
    } else if (method === 'Page.frameNavigated') {
      // P5: track a top-frame commit so evaluate can tell an error page from a
      // working one. A successful document clears the error state.
      const frame = params.frame || {};
      if (!frame.parentId) {
        const fu = String(frame.url || '');
        if (/^chrome-error:\/\//i.test(fu)) {
          errorPage = {
            url: fu,
            unreachableUrl: String(frame.unreachableUrl || ''),
            at: Date.now(),
          };
        } else if (fu && !/^about:blank$/i.test(fu)) {
          errorPage = null;
        }
      }
    } else if (method === 'Page.downloadWillBegin' || method === 'Browser.downloadWillBegin') {
      // P5: an attachment navigation starts a download without changing the
      // page. Record it (served by list_downloads / probe) and notify the
      // daemon so the triggering command's response can say what happened.
      const rec = {
        guid: String(params.guid || ''),
        url: typeof params.url === 'string' ? params.url : '',
        suggestedFilename: typeof params.suggestedFilename === 'string'
          ? params.suggestedFilename : '',
        state: 'started',
        at: Date.now(),
      };
      lastDownload = rec;
      ringPush(downloadRecords, rec);
      notifyDaemon({
        kind: 'download_started',
        text: 'download started: ' + (rec.suggestedFilename || '(unnamed)') +
              (rec.url ? ' <- ' + rec.url : ''),
        download: rec,
      });
    } else if (method === 'Page.downloadProgress' || method === 'Browser.downloadProgress') {
      // Fold progress into the matching record (bounded ring, newest last).
      const guid = String(params.guid || '');
      const rec = downloadRecords.find((d) => d.guid === guid) || lastDownload;
      if (rec && rec.guid === guid) {
        if (typeof params.state === 'string') rec.state = params.state;
        if (typeof params.receivedBytes === 'number') rec.receivedBytes = params.receivedBytes;
        if (typeof params.totalBytes === 'number') rec.totalBytes = params.totalBytes;
      }
    } else if (method === 'Page.fileChooserOpened') {
      // A file input / custom upload control was clicked and Chrome's native
      // dialog was intercepted (setInterceptFileChooserDialog on attach) — the
      // page is NOT blocked; record the chooser so handle_file_chooser can
      // fill it via DOM.setFileInputFiles. Newest opening overwrites (a stale
      // chooser older than ~10 s is replaced by this one anyway).
      pendingFileChooser = {
        backendNodeId: params.backendNodeId,
        frameId: typeof params.frameId === 'string' ? params.frameId : '',
        mode: typeof params.mode === 'string' ? params.mode : 'selectSingle',
        openedAt: Date.now(),
      };
    }
  } catch (_) { /* a malformed event must never break the session */ }
});

// One CDP command shared by the evaluate action and the probe's P7. A
// transport-level rejection while we believed the session was live means the
// session is dead — reset it so the next evaluate attaches a fresh one, then
// rethrow so the caller turns it into {ok:false, error}.
async function runtimeEvaluate(tabId, expression) {
  try {
    return await sendCdp(tabId, 'Runtime.evaluate', {
      expression,
      returnByValue: true,   // send the completion value as JSON
      awaitPromise: true,    // await a Promise completion value
      userGesture: true,     // treat as user-initiated
      replMode: true,        // console-style evaluation: a re-run of a
                             // snippet that redeclares top-level let/const/
                             // class no longer raises "already declared"
                             // (the DevTools console semantics)
    });
  } catch (err) {
    if (!err.dialogBlocking && debuggerTabId === tabId) {
      attachedTabs.delete(tabId);
      debuggerTabId = null;
      chrome.debugger.detach({ tabId }).catch(() => { /* noop */ });
    }
    throw err;
  }
}

// ---------------- popup runtime messages ----------------
// The toolbar popup (popup.html) talks to this service worker over
// chrome.runtime messages — no daemon WebSocket is involved:
//   {type: "wf-ping"}              -> {ok:true, version, suspended, daemon: "connected"|"disconnected"}
//        (suspended:true means the user paused the link from the popup — the
//         UI shows Disconnected even if the daemon itself is reachable)
//   {type: "wf-disconnect"}        -> {ok:true, suspended:true}  (close + pause)
//   {type: "wf-reconnect"}         -> {ok:true, suspended:false} (resume now)
//   {type: "wf-dial-now"}          -> {ok, state, reason?}
//        (cancel the backoff timer and dial this instant; reason is
//         'daemon_down' when no daemon answers, 'daemon_busy' when the daemon
//         is up but the handshake is refused / the slot is held)
//   {type: "wf-evaluate", code}    -> {ok:true, value} | {ok:false, error}
//        (active tab; routed through the SHARED debugger session helpers
//         below — ensureDebugger + runtimeEvaluate — never re-implemented)
// Every branch resolves a reply, so the listener never throws uncaught.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg !== 'object') return;

  if (msg.type === 'wf-ping') {
    suspendStateReady.then(() => {
      sendResponse({
        ok: true,
        version: chrome.runtime.getManifest().version,
        suspended: suspended,
        daemon: (ws && ws.readyState === WebSocket.OPEN) ? 'connected' : 'disconnected',
      });
    });
    return true;        // cold start: the persisted flag read may still be pending
  }

  if (msg.type === 'wf-disconnect') {
    suspendConnection().then(() => sendResponse({ ok: true, suspended: true }));
    return true;        // reply after the durable write
  }

  if (msg.type === 'wf-reconnect') {
    resumeConnection().then(() => sendResponse({ ok: true, suspended: false }));
    return true;        // reply after the durable write
  }

  if (msg.type === 'wf-dial-now') {
    dialNow().then((out) => sendResponse(out));
    return true;        // reply after the dial attempt settles
  }

  if (msg.type === 'wf-evaluate') {
    const code = (typeof msg.code === 'string' && msg.code.trim())
      ? msg.code
      : '(() => document.title)()';
    (async () => {
      let resp;
      try {
        const tab = await activeTab();            // ACTIVE tab of this window
        resp = await evaluateOnTab(tab, code);
      } catch (err) {
        resp = { ok: false, error: String((err && err.message) || err) };
      }
      sendResponse(resp.ok
        ? { ok: true, value: resp.value }
        : { ok: false, error: resp.error });
    })();
    return true;        // keep the channel open for the async reply
  }
});

// ---------------- command handling ----------------

async function handleMessage(ev) {
  let msg;
  try { msg = JSON.parse(ev.data); } catch (_) { return; }
  if (!msg || typeof msg !== 'object') return;
  // P1: daemon -> extension control frames carry no request id (no reply).
  if (msg.type === 'set_dialog_policy') {
    if (msg.policy === 'auto-accept' || msg.policy === 'manual') {
      dialogPolicy = msg.policy;
    }
    return;
  }
  if (!msg.id) return;   // ping etc.

  try {
    if (msg.action === 'navigate') {
      await handleNavigate(msg);
    } else if (msg.action === 'cdp') {
      await handleCdp(msg);                   // generic chrome.debugger passthrough
    } else if (msg.action === 'tabs_list') {
      await handleTabsList(msg);
    } else if (msg.action === 'tabs_close') {
      await handleTabsClose(msg);
    } else if (msg.action === 'tabs_activate') {
      await handleTabsActivate(msg);
    } else if (msg.action === 'tabs_open') {
      await handleTabsOpen(msg);
    } else if (msg.action === 'tabs_close_all_but') {
      await handleTabsCloseAllBut(msg);
    } else if (msg.action === 'probe') {
      await handleProbe(msg);                 // diagnostic path matrix; never throws
    } else if (msg.action === 'find_tab') {
      await handleFindTab(msg);
    } else if (msg.action === 'snapshot') {
      await handleSnapshot(msg);
    } else if (msg.action === 'click') {
      await handleClick(msg);
    } else if (msg.action === 'fill') {
      await handleFill(msg);
    } else if (msg.action === 'screenshot') {
      await handleScreenshot(msg);
    } else if (msg.action === 'upload') {
      await handleUpload(msg);
    } else if (msg.action === 'save_as_pdf') {
      await handleSaveAsPdf(msg);
    } else if (msg.action === 'mouse_click') {
      await handleMouseClick(msg);
    } else if (msg.action === 'send_key') {
      await handleSendKey(msg);
    } else if (msg.action === 'type_text') {
      await handleTypeText(msg);
    } else if (msg.action === 'submit') {
      await handleSubmit(msg);
    } else if (msg.action === 'fill_form') {
      await handleFillForm(msg);
    } else if (msg.action === 'wait_for') {
      await handleWaitFor(msg);
    } else if (msg.action === 'handle_dialog') {
      await handleDialog(msg);
    } else if (msg.action === 'set_dialog_policy') {
      handleSetDialogPolicy(msg);
    } else if (msg.action === 'list_downloads') {
      handleListDownloads(msg);
    } else if (msg.action === 'handle_file_chooser') {
      await handleFileChooser(msg);
    } else if (msg.action === 'drop') {
      await handleDrop(msg);
    } else if (msg.action === 'resize_page') {
      await handleResizePage(msg);
    } else if (msg.action === 'list_network_requests') {
      await handleListNetworkRequests(msg);
    } else if (msg.action === 'get_network_request') {
      await handleGetNetworkRequest(msg);
    } else if (msg.action === 'list_console_messages') {
      await handleListConsoleMessages(msg);
    } else {                                  // evaluate (default)
      await handleEvaluate(msg);
    }
  } catch (err) {
    send({ id: msg.id, ok: false,
           error: String((err && err.message) || err) });
  }
}

// Run `code` on an already-resolved tab through the SHARED debugger session
// manager (ensureDebugger + runtimeEvaluate) — the same path the WS evaluate
// action takes, so attach logic is never duplicated. Returns
// {ok:true, value} or {ok:false, error}; never throws.
async function evaluateOnTab(tab, code) {
  // A pending dialog on THIS tab fast-fails in ms even when the session is
  // currently attached elsewhere: switching back to a blocked tab must not
  // first pay the ~10 s attach-time domain-setup budget (and must not be
  // affected by a dialog on a different tab).
  const knownDialog = nativeDialogBlockError(tab.id);
  if (knownDialog) return { ok: false, error: knownDialog.message };
  const attachError = await ensureDebugger(tab.id);
  if (attachError) {
    return { ok: false, error: classifyPageFailure(tab, attachError) || attachError };
  }

  // P5: a committed browser error page is not a page to evaluate against —
  // report the classified reason instead of returning the error page's values.
  const pageProblem = classifyPageFailure(tab, '');
  if (pageProblem) return { ok: false, error: pageProblem };

  let resp;
  try {
    resp = await runtimeEvaluate(tab.id, code);
  } catch (err) {
    const text = String((err && err.message) || err);
    return { ok: false, error: classifyPageFailure(tab, text) || text };
  }

  if (resp.exceptionDetails) {
    // The snippet threw (or its Promise rejected). Keep the reply small.
    return { ok: false, error: JSON.stringify(resp.exceptionDetails).slice(0, 500) };
  }

  const result = resp.result || {};           // CDP RemoteObject
  let value;
  if (result.value !== undefined || result.type === 'object') {
    // Normal case: returnByValue puts the JSON-safe payload in .value
    // (objects arrive as {type:'object', value:{...}}).
    value = result.value;
  } else {
    // Completion value is undefined/function/symbol/...: send a small
    // JSON-safe marker of the RemoteObject instead of the raw handle.
    value = { type: result.type };
  }
  return { ok: true, value: jsonSafe(value) };
}

// P5: make the three very different "cannot act on this page" reasons look
// different to a caller (protected page / failed-or-certificate-error page /
// no debuggable target). Returns null when the error is unrelated (the
// original message is then passed through untouched).
function classifyPageFailure(tab, errorText) {
  const url = (tab && tab.url) || '';
  const err = String(errorText || '');
  if (errorPage && /^chrome-error:\/\//i.test(errorPage.url || '')) {
    const target = errorPage.unreachableUrl || url || 'unknown';
    return 'page failed to load — network error, certificate error, or a ' +
           'native authentication prompt that was cancelled (unreachable: ' +
           target + '); the tab is showing the browser error page ' +
           '(chrome-error://chromewebdata/); navigate to a working page and ' +
           'retry';
  }
  if (/^(chrome|edge)-error:\/\//i.test(url)) {
    return 'page failed to load — network error, certificate error, or a ' +
           'native authentication prompt that was cancelled (browser error ' +
           'page: ' + url + '); navigate to a working page and retry';
  }
  if (/^(chrome|edge):\/\//i.test(url) ||
      /chromewebstore\.google\.com|microsoftedge\.microsoft\.com/i.test(url)) {
    return 'protected page — the browser does not allow debugger access to ' +
           url + '; open a normal http(s) page';
  }
  if (/cannot attach to this target/i.test(err)) {
    return 'cannot attach to this target — it is either a protected page ' +
           '(chrome:// / Web Store) or a failed / certificate-error page ' +
           '(url: ' + (url || 'unknown') + ')';
  }
  if (/ERR_CERT|SSL|certificate/i.test(err)) {
    return 'certificate error while loading the page: ' + err;
  }
  if (/net::ERR_/i.test(err)) {
    return 'page failed to load (network error): ' + err;
  }
  return null;
}

async function handleEvaluate(msg) {
  if (typeof msg.code !== 'string') throw new Error('missing code');
  // An explicit tabId targets that tab: chrome.tabs.get resolves it (and
  // throws when the tab is gone -> {ok:false, error}). Without one the ACTIVE
  // tab is used, exactly as before.
  const tab = (typeof msg.tabId === 'number')
    ? await chrome.tabs.get(msg.tabId)
    : await activeTab();
  const result = await evaluateOnTab(tab, msg.code);
  if (result.ok) {
    if (msg.humanize === true) {
      // P1: before the reply, a best-effort scroll micro-move (±10 px) so
      // successive page reads are not perfectly static. Never fatal.
      try { await evaluateOnTab(tab, humanizeScrollExpression()); }
      catch (_) { /* micro scroll is best-effort */ }
    }
    send({ id: msg.id, ok: true, value: result.value });
  } else send({ id: msg.id, ok: false, error: result.error });
}

// ---------------- generic CDP passthrough + tab management ----------------

// Resolve the tab an action targets: an explicit numeric tabId in the message
// wins; otherwise the active tab of the current window.
async function targetTabId(msg) {
  if (typeof msg.tabId === 'number') return msg.tabId;
  return (await activeTab()).id;
}

// "cdp": fire ANY Chrome DevTools Protocol method through the managed
// chrome.debugger session ({method, params?, tabId?}). No method allowlist —
// this is a local personal tool, and whatever chrome.debugger can reach
// (Input.*, Page.*, DOM.*, Network.*, Runtime.*, ...) is exposed. The raw CDP
// command result (a JSON-safe plain object) is the reply value.
async function handleCdp(msg) {
  const method = msg.method;
  if (typeof method !== 'string' || !method.trim()) throw new Error('missing method');
  const tabId = await targetTabId(msg);

  // Validating the tab exists also fails fast on stale tabIds. When the
  // requested tabId differs from the one the session is attached to,
  // ensureDebugger switches the session (detach old, attach new) before the
  // command below runs.
  await chrome.tabs.get(tabId);

  const attachError = await ensureDebugger(tabId);
  if (attachError) {
    send({ id: msg.id, ok: false, error: attachError });
    return;
  }

  const params = (msg.params && typeof msg.params === 'object' &&
                  !Array.isArray(msg.params)) ? msg.params : {};
  let result;
  try {
    result = await sendCdp(tabId, method, params);
  } catch (err) {
    // Transport-level rejection while we believed the session was live means
    // the session died — reset it (same logic runtimeEvaluate uses) so the
    // next command attaches a fresh one, then report the failure. A deliberate
    // dialog fast-fail keeps the session (see dialogBlockingError).
    if (!err.dialogBlocking && debuggerTabId === tabId) {
      attachedTabs.delete(tabId);
      debuggerTabId = null;
      chrome.debugger.detach({ tabId }).catch(() => { /* noop */ });
    }
    send({ id: msg.id, ok: false,
           error: String((err && err.message) || err) });
    return;
  }
  send({ id: msg.id, ok: true, value: jsonSafe(result) });
}

// "tabs_list": snapshot every tab as {id, url, title, active, windowId,
// index}, omitting undefined fields. Protected pages (chrome://, Web Store,
// new-tab) may expose no url/title — they are included with whatever the tabs
// API provides, so scripts can pick a tabId for cdp/tabs_close/tabs_activate.
async function handleTabsList(msg) {
  const tabs = await chrome.tabs.query({});
  const value = tabs.map((tab) => {
    const item = {};
    for (const key of ['id', 'url', 'title', 'active', 'windowId', 'index']) {
      if (tab[key] !== undefined) item[key] = tab[key];
    }
    return item;
  });
  send({ id: msg.id, ok: true, value });
}

// "tabs_close": close the given tab (default: active tab). Closing the last
// tab of a window may close the window — accepted; if the closed tab owned
// the debugger session, onDetach nulls the stale state automatically.
async function handleTabsClose(msg) {
  const tabId = await targetTabId(msg);
  await chrome.tabs.remove(tabId);
  send({ id: msg.id, ok: true, value: { closed: tabId } });
}

// "tabs_activate": bring a tab to the front of its window and focus that
// window. Focusing can be denied without extra permissions — non-fatal; the
// tab is active either way.
async function handleTabsActivate(msg) {
  const tabId = await targetTabId(msg);
  await chrome.tabs.update(tabId, { active: true });
  try {
    const tab = await chrome.tabs.get(tabId);
    await chrome.windows.update(tab.windowId, { focused: true });
  } catch (_) { /* window focus may be denied; activation already succeeded */ }
  send({ id: msg.id, ok: true, value: { tabId, active: true } });
}

// "tabs_open": open a new tab with the given http(s) url. Reply value is
// {id, url} straight from the created chrome.tabs.Tab object.
async function handleTabsOpen(msg) {
  const url = msg.url;
  if (typeof url !== 'string' || !/^https?:/i.test(url.trim())) {
    throw new Error('url must be an http(s) string');
  }
  const tab = await chrome.tabs.create({ url });
  send({ id: msg.id, ok: true, value: { id: tab.id, url: tab.url } });
}

// "tabs_close_all_but": close every tab in the SAME window as tabId (default:
// active tab) except tabId itself, one chrome.tabs.remove per tab. Closing the
// last tab of a window (Chrome closes the window) is still attempted; a failed
// removal surfaces as the usual {ok:false, error}. Reply value {closed: count}.
async function handleTabsCloseAllBut(msg) {
  const tabId = await targetTabId(msg);
  const keep = await chrome.tabs.get(tabId);          // throws if tab is gone
  const tabs = await chrome.tabs.query({ windowId: keep.windowId });
  let closed = 0;
  for (const tab of tabs) {
    if (tab.id === tabId) continue;
    try {
      await chrome.tabs.remove(tab.id);
      closed += 1;
    } catch (err) {
      send({ id: msg.id, ok: false,
             error: String((err && err.message) || err) });
      return;
    }
  }
  send({ id: msg.id, ok: true, value: { closed } });
}

// ---------------- find_tab / snapshot / click / fill -------------
// Phase-A agent tools with standard browser-bridge-compatible names. Every
// page read/write goes through Runtime.evaluate snippets on the managed
// chrome.debugger session (the same channel the evaluate action uses) — no
// content scripts, no new permissions. snapshot caches "@eN" -> CSS path so
// click/fill can address elements by ref against the SAME tab.

// Last successful snapshot cache. byRef maps "@e{i}" -> CSS path; byIndex is
// the same list in emitted-node order (byRef["@e"+i] === byIndex[i]).
let lastSnapshot = null;        // {tabId, byRef, byIndex}

// Resolve a click/fill target to a CSS path string that every evaluate
// snippet below re-queries. "@eN" refs resolve through lastSnapshot and
// REQUIRE the snapshot to have been taken on the same tab (a stale or missing
// snapshot is an error); anything else is a plain CSS selector, validated at
// evaluate time. `index` is the alt spelling of the numeric part of an @e
// ref: selector "@e" + index N == "@eN".
function resolveElement(tabId, selector, index) {
  let sel = (typeof selector === 'string') ? selector.trim() : '';
  if (sel === '@e' && Number.isInteger(index) && index >= 0) {
    sel = '@e' + index;
  }
  if (sel === '@e') {
    throw new Error("snapshot ref '@e' needs an index: use '@eN' or pass index");
  }
  if (!sel) throw new Error('missing selector');
  if (/^@e\d+$/.test(sel)) {
    if (!lastSnapshot || lastSnapshot.tabId !== tabId) {
      throw new Error('snapshot stale — call snapshot again');
    }
    const path = lastSnapshot.byRef[sel];
    if (typeof path !== 'string' || !path) {
      throw new Error('snapshot ref not found: ' + sel +
                      ' — call snapshot again');
    }
    return path;
  }
  return sel;
}

// Kind of URL match for find_tab: 2 = exact, 1 = the tab URL starts with the
// needle (prefix), 0 = the needle appears inside the tab URL (substring), null
// = no full match.
function findTabMatchKind(url, needle) {
  if (url === needle) return 2;
  if (url.startsWith(needle)) return 1;
  if (url.indexOf(needle) !== -1) return 0;
  return null;
}

// Length of the longest common SUBSTRING of a and b (rolling DP). Only used
// for find_tab's fallback pass, so O(n*m) over short URLs is fine.
function longestCommonSubstringLength(a, b) {
  if (!a || !b) return 0;
  const row = new Array(b.length + 1).fill(0);
  let best = 0;
  for (let i = 1; i <= a.length; i += 1) {
    let diag = 0;                             // dp[i-1][j-1]
    for (let j = 1; j <= b.length; j += 1) {
      const up = row[j];                      // dp[i-1][j]
      row[j] = (a.charCodeAt(i - 1) === b.charCodeAt(j - 1)) ? diag + 1 : 0;
      if (row[j] > best) best = row[j];
      diag = up;                              // becomes dp[i-1][j] for j+1
    }
  }
  return best;
}

// "find_tab": locate an open tab whose URL matches `url`. Every tab of the
// CURRENT window is searched first, then every other window (chrome.tabs.query
// order). Candidates are ranked deterministically — exact first, then by
// matched-URL length (the more specific, longer URL wins), ties broken by
// current-window-first search order via a stable sort. When no tab contains
// the full needle, a longest-common-substring fallback accepts the tab with
// the most overlap (>= half the needle, minimum 4 chars). Never creates a
// tab; with active:true the matched tab is activated. The extension reply is
// {id, ok:true, value:{success, url, tabId}} or {success:false, error}.
async function handleFindTab(msg) {
  const needle = msg.url;
  if (typeof needle !== 'string' || !needle.trim()) throw new Error('missing url');
  const activate = msg.active === true;

  const current = await chrome.tabs.query({ currentWindow: true });
  const currentIds = new Set(current.map((tab) => tab.id));
  const all = await chrome.tabs.query({});
  const ordered = current.concat(all.filter((tab) => !currentIds.has(tab.id)));

  const candidates = [];
  for (const tab of ordered) {
    const url = tab.url;
    if (typeof url !== 'string' || !url) continue;
    const kind = findTabMatchKind(url, needle);
    if (kind !== null) candidates.push({ tab, url, kind });
  }
  if (candidates.length) {
    // Stable sort: exact (kind 2) first, then prefix (1), then substring (0);
    // inside a kind the longer (more specific) URL wins; ties keep the
    // current-window-first order of `ordered`.
    candidates.sort((a, b) =>
      (b.kind - a.kind) || (b.url.length - a.url.length));
    const best = candidates[0];
    if (activate) await chrome.tabs.update(best.tab.id, { active: true });
    send({ id: msg.id, ok: true,
           value: { success: true, url: best.url, tabId: best.tab.id } });
    return;
  }

  // Fallback: no full match anywhere — longest common substring.
  let bestTab = null;
  let bestScore = 0;
  for (const tab of ordered) {
    const url = tab.url;
    if (typeof url !== 'string' || !url) continue;
    const score = longestCommonSubstringLength(url, needle);
    if (score > bestScore) {
      bestScore = score;
      bestTab = tab;
    }
  }
  const minOverlap = Math.max(4, Math.floor(needle.length * 0.5));
  if (bestTab && bestScore >= minOverlap) {
    if (activate) await chrome.tabs.update(bestTab.id, { active: true });
    send({ id: msg.id, ok: true,
           value: { success: true, url: bestTab.url, tabId: bestTab.id } });
    return;
  }
  send({ id: msg.id, ok: true,
         value: { success: false, error: 'no tab matches ' + needle } });
}

// One evaluate snippet implementing the whole snapshot: single querySelectorAll
// over a composite selector (fast pre-filter), then per-element JS filtering
// for visibility + allowed type + role/text/name extraction + a robust CSS
// path (tag:nth-of-type(n) chain up to document.body, capped at 40 levels,
// truncated from the root side when deeper). Runs in the main frame only
// (Runtime.evaluate without a contextId; iframes are ignored this pass). Each
// element is guarded so a mid-walk change (e.g. a detached node) skips it
// instead of failing the snapshot.
function snapshotExpression(start, limit) {
  return `(() => {
  const START = ${start};
  const LIMIT = ${limit};
  const ROLE_OK = new Set(["button", "link", "textbox", "combobox", "checkbox", "radio", "menuitem", "tab", "option"]);
  const SEL = 'a[href],button,input:not([type="hidden"]),textarea,select,[contenteditable],[role],[summary],img[alt]';
  function isVisible(el) {
    // Visible rule: laid out (offsetParent) or painted (has rects) — covers
    // position:fixed whose offsetParent is null.
    if (el.offsetParent === null) {
      if (!el.getClientRects || el.getClientRects().length === 0) return false;
    }
    return true;
  }
  function isAllowed(el) {
    const tag = el.tagName;
    if (tag === "A") return el.hasAttribute("href");
    if (tag === "BUTTON" || tag === "SUMMARY" || tag === "TEXTAREA" || tag === "SELECT") return true;
    if (tag === "INPUT") return (el.type || "text").toLowerCase() !== "hidden";
    if (tag === "IMG") {
      const alt = el.getAttribute("alt");
      return typeof alt === "string" && alt.trim() !== "";
    }
    const ce = el.getAttribute("contenteditable");
    if (ce === "" || ce === "true" || ce === "plaintext-only") return true;
    const role = el.getAttribute("role");
    return !!(role && ROLE_OK.has(String(role).toLowerCase()));
  }
  // Control types an agent interacts with: form controls, contenteditable
  // editors, and interactive roles. Controls are ALWAYS kept in the snapshot
  // even when their text/name is empty — an empty input / empty contenteditable
  // is exactly the element an agent needs to fill (the empty-text skip below
  // only applies to non-control containers).
  function isControl(el) {
    const tag = el.tagName;
    if (tag === "INPUT") return (el.type || "text").toLowerCase() !== "hidden";
    if (tag === "TEXTAREA" || tag === "SELECT") return true;
    const ce = el.getAttribute && el.getAttribute("contenteditable");
    if (ce === "" || ce === "true" || ce === "plaintext-only") return true;
    const role = el.getAttribute("role");
    if (role) return ROLE_OK.has(String(role).toLowerCase());
    return false;
  }
  function roleOf(el) {
    const r = el.getAttribute("role");
    if (r) return String(r).toLowerCase();
    const tag = el.tagName;
    if (tag === "A") return "link";
    if (tag === "BUTTON") return "button";
    if (tag === "TEXTAREA") return "textbox";
    if (tag === "SELECT") return "combobox";
    if (tag === "INPUT") {
      const ty = (el.type || "text").toLowerCase();
      if (ty === "checkbox") return "checkbox";
      if (ty === "radio") return "radio";
      if (ty === "button" || ty === "submit" || ty === "reset" || ty === "image") return "button";
      return "textbox";
    }
    return "";
  }
  function nameOf(el, text) {
    // A control with empty text is a "fill me" target — never leave its name
    // empty: placeholder -> aria-label -> title -> id.
    if (isControl(el) && !text) {
      const ph = el.getAttribute && el.getAttribute("placeholder");
      if (ph && String(ph).trim()) return ph;
      const al = el.getAttribute("aria-label");
      if (al && String(al).trim()) return al;
      const ti = el.getAttribute("title");
      if (ti && String(ti).trim()) return ti;
      const id = el.id;
      if (typeof id === "string" && id.trim()) return id;
      return "";
    }
    const al = el.getAttribute("aria-label");
    if (al && String(al).trim()) return al;
    const ti = el.getAttribute("title");
    if (ti && String(ti).trim()) return ti;
    if (el.tagName === "IMG") {
      const alt = el.getAttribute("alt");
      if (alt) return alt;
    }
    return "";
  }
  function textOf(el) {
    const tag = el.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") {
      const ty = (el.type || "text").toLowerCase();
      if (ty === "checkbox" || ty === "radio") return "";   // label, not "on"
      const v = el.value;
      return typeof v === "string" ? v.trim().slice(0, 120) : "";
    }
    const t = (el.innerText || "").replace(/\\s+/g, " ").trim();
    return t.slice(0, 120);
  }
  function cssPath(el) {
    const parts = [];
    let cur = el;
    while (cur && cur.parentElement && cur !== document.body) {
      const parent = cur.parentElement;
      let nth = 1;
      for (let s = cur.previousElementSibling; s; s = s.previousElementSibling) {
        if (s.tagName === cur.tagName) nth += 1;
      }
      parts.push(cur.tagName.toLowerCase() + ":nth-of-type(" + nth + ")");
      cur = parent;
    }
    parts.reverse();
    if (parts.length > 40) parts.splice(0, parts.length - 40);
    return parts.join(" > ");
  }
  let els;
  try {
    els = document.querySelectorAll(SEL);
  } catch (err) {
    return { error: "snapshot failed: " + String((err && err.message) || err) };
  }
  const out = [];
  let total = 0;
  for (let i = 0; i < els.length; i += 1) {
    const el = els[i];
    try {
      if (!isVisible(el) || !isAllowed(el)) continue;
      const path = cssPath(el);
      const text = textOf(el);
      const name = nameOf(el, text);
      const role = roleOf(el);
      // Empty-text skip applies to NON-control containers only; controls are
      // always kept (empty inputs / contenteditable editors are fill targets).
      if (!isControl(el) && !name && !text && !role) continue;
      total += 1;
      if (total <= START) continue;                // element before this page
      if (out.length >= LIMIT) continue;           // page full; keep counting total
      out.push({
        ref: "@e" + (total - 1),   // FULL-list index — stable across pages
        tag: el.tagName.toLowerCase(),
        role: role,
        name: name,
        text: text,
        path: path,
      });
    } catch (err) { /* element changed mid-walk (detached) — skip it */ }
  }
  return { url: location.href, title: document.title, total: total,
           start: START, nodes: out };
})()`;
}

// "click" evaluate snippet: query the (re-resolved) path, scroll it into view,
// el.click(), and echo {success, tag, text}. Every failure returns {error}
// from inside the snippet so the WS reply stays {ok:false, error} with a clean
// message.
function clickExpression(sel) {
  return `(() => {
  try {
    const sel = ${JSON.stringify(sel)};
    const el = document.querySelector(sel);
    if (!el) return { error: "element not found: " + sel };
    if (typeof el.scrollIntoView === "function") {
      try { el.scrollIntoView({ block: "center", inline: "center" }); } catch (err) { /* noop */ }
    }
    el.click();
    return {
      success: true,
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.getAttribute("aria-label") || "").slice(0, 80),
    };
  } catch (err) {
    return { error: String((err && err.message) || err) };
  }
})()`;
}

// Classify the resolved element for fill's mode selection: tag + whether it is
// a form control (value-fillable) or a contenteditable region.
function classifyExpression(sel) {
  return `(() => {
  try {
    const sel = ${JSON.stringify(sel)};
    const el = document.querySelector(sel);
    if (!el) return { error: "element not found: " + sel };
    const tag = (el.tagName || "").toLowerCase();
    const ce = el.getAttribute ? el.getAttribute("contenteditable") : null;
    return {
      tag: tag,
      isValue: tag === "input" || tag === "textarea" || tag === "select",
      editable: !!(el.isContentEditable || ce === "" || ce === "true" || ce === "plaintext-only"),
    };
  } catch (err) {
    return { error: String((err && err.message) || err) };
  }
})()`;
}

// Fill a form control through the NATIVE value setter so React/DOM frameworks
// observe a real input (the known React trick), then fire input/change. A
// SELECT is set directly + a change event (per design).
function valueFillExpression(sel, value) {
  return `(() => {
  try {
    const sel = ${JSON.stringify(sel)};
    const value = ${JSON.stringify(value)};
    const el = document.querySelector(sel);
    if (!el) return { error: "element not found: " + sel };
    const tag = el.tagName;
    if (tag === "SELECT") {
      el.value = value;
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } else if (tag === "INPUT" || tag === "TEXTAREA") {
      const proto = tag === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) {
        desc.set.call(el, value);
      } else {
        el.value = value;
      }
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      return { error: "unsupported element for fill: <" + tag.toLowerCase() + ">" };
    }
    return { success: true };
  } catch (err) {
    return { error: String((err && err.message) || err) };
  }
})()`;
}

// Focus the contenteditable region (scroll into view + el.focus()) so the CDP
// Input.insertText that follows types at the caret.
function focusExpression(sel) {
  return `(() => {
  try {
    const sel = ${JSON.stringify(sel)};
    const el = document.querySelector(sel);
    if (!el) return { error: "element not found: " + sel };
    if (typeof el.scrollIntoView === "function") {
      try { el.scrollIntoView({ block: "center" }); } catch (err) { /* noop */ }
    }
    el.focus();
    return { success: true, tag: el.tagName.toLowerCase() };
  } catch (err) {
    return { error: String((err && err.message) || err) };
  }
})()`;
}

// "snapshot": a11y-style snapshot of the targeted tab (active unless tabId is
// given), cached in lastSnapshot for @e ref resolution. value = {url, title,
// nodes:[{ref, tag, role, name, text, path}]} capped at max (default 400).
async function handleSnapshot(msg) {
  const tabId = await targetTabId(msg);
  const tab = await chrome.tabs.get(tabId);   // fail fast on stale ids
  let start = 0;
  if (Number.isInteger(msg.start) && msg.start > 0) start = msg.start;
  let max = 400;
  if (Number.isInteger(msg.max) && msg.max > 0) max = Math.min(msg.max, 5000);
  const result = await evaluateOnTab(tab, snapshotExpression(start, max));
  if (!result.ok) {
    send({ id: msg.id, ok: false, error: result.error });
    return;
  }
  const value = (result.value && typeof result.value === 'object')
    ? result.value : {};
  if (value.error) {
    send({ id: msg.id, ok: false, error: value.error });
    return;
  }
  const nodes = Array.isArray(value.nodes) ? value.nodes : [];
  // @e refs are FULL-list indices; a later page (start > 0) MERGES into the
  // cache so refs from earlier pages keep resolving until the DOM changes or
  // a fresh start=0 snapshot resets the cache.
  if (start === 0 || !lastSnapshot || lastSnapshot.tabId !== tabId) {
    lastSnapshot = { tabId, byRef: {}, byIndex: [] };
  }
  for (let i = 0; i < nodes.length; i += 1) {
    const node = nodes[i] || {};
    const ref = node.ref;
    const path = node.path;
    if (typeof ref !== 'string' || typeof path !== 'string' || !path) continue;
    lastSnapshot.byRef[ref] = path;
    lastSnapshot.byIndex.push(path);
  }
  send({ id: msg.id, ok: true, value: {
    url: value.url || null, title: value.title || null,
    total: (typeof value.total === 'number') ? value.total : nodes.length,
    start,
    nodes,
  } });
}

// "click": click an element addressed by a CSS selector or a snapshot "@eN"
// ref on the same tab. The @e path is re-resolved in the page at click time,
// so small DOM shifts are tolerated; a fully stale ref surfaces as an
// "element not found" {ok:false, error}.
async function handleClick(msg) {
  if (msg.humanize === true) await humanizeDelay(200, 900);  // P1 pre-delay
  const tabId = await targetTabId(msg);
  const path = resolveElement(tabId, msg.selector, msg.index);
  const tab = await chrome.tabs.get(tabId);
  const result = await evaluateOnTab(tab, clickExpression(path));
  if (!result.ok) {
    send({ id: msg.id, ok: false, error: result.error });
    return;
  }
  const value = result.value || {};
  if (value.error) {
    send({ id: msg.id, ok: false, error: value.error });
    return;
  }
  send({ id: msg.id, ok: true, value });
}

// "fill": fill a form control or type into a contenteditable region.
//   auto (default): classify the resolved element — input/textarea/select
//     -> "value", a contenteditable region -> "contenteditable", else an
//     "unsupported element" error.
//   value: native value setter + input/change events (React/DOM-safe).
//   contenteditable: focus through the page (evaluate snippet), then type
//     through CDP Input.insertText on the already-attached session — the
//     proven path the publish scripts use today — then wait 300 ms.
// value reply = {success:true, tag, mode:<actual mode used>}.
async function handleFill(msg) {
  if (typeof msg.value !== 'string') throw new Error('missing value');
  if (msg.humanize === true) await humanizeDelay(200, 900);  // P1 pre-delay
  const requested = (typeof msg.mode === 'string' ? msg.mode : 'auto').toLowerCase();
  const mode = (requested === 'value' || requested === 'contenteditable')
    ? requested : 'auto';

  const tabId = await targetTabId(msg);
  const path = resolveElement(tabId, msg.selector);
  const tab = await chrome.tabs.get(tabId);

  // Classify first so "auto" (and the mode guards) pick the right path.
  const cls = await evaluateOnTab(tab, classifyExpression(path));
  if (!cls.ok) {
    send({ id: msg.id, ok: false, error: cls.error });
    return;
  }
  const c = cls.value || {};
  if (c.error) {
    send({ id: msg.id, ok: false, error: c.error });
    return;
  }

  let actual;
  if (mode === 'auto') {
    if (c.isValue) actual = 'value';
    else if (c.editable) actual = 'contenteditable';
    else {
      send({ id: msg.id, ok: false,
             error: 'unsupported element for fill: <' + c.tag +
                    '> (expects input/textarea/select or contenteditable)' });
      return;
    }
  } else if (mode === 'value') {
    if (!c.isValue) {
      send({ id: msg.id, ok: false,
             error: 'element <' + c.tag +
                    '> is not an input/textarea/select (mode="value")' });
      return;
    }
    actual = 'value';
  } else {
    if (!c.editable) {
      send({ id: msg.id, ok: false,
             error: 'element <' + c.tag +
                    '> is not contenteditable (mode="contenteditable")' });
      return;
    }
    actual = 'contenteditable';
  }

  if (actual === 'value') {
    const r = await evaluateOnTab(tab, valueFillExpression(path, msg.value));
    if (!r.ok) {
      send({ id: msg.id, ok: false, error: r.error });
      return;
    }
    const rv = r.value || {};
    if (rv.error) {
      send({ id: msg.id, ok: false, error: rv.error });
      return;
    }
    send({ id: msg.id, ok: true,
           value: { success: true, tag: c.tag, mode: 'value' } });
    return;
  }

  // contenteditable: focus through the page, type through the CDP session.
  const f = await evaluateOnTab(tab, focusExpression(path));
  if (!f.ok) {
    send({ id: msg.id, ok: false, error: f.error });
    return;
  }
  const fv = f.value || {};
  if (fv.error) {
    send({ id: msg.id, ok: false, error: fv.error });
    return;
  }
  const attachError = await ensureDebugger(tabId);
  if (attachError) {
    send({ id: msg.id, ok: false, error: attachError });
    return;
  }
  try {
    if (msg.humanize === true) await humanizeDelay(30, 120);  // P1 jitter
    await sendCdp(tabId, 'Input.insertText', { text: msg.value });
  } catch (err) {
    send({ id: msg.id, ok: false,
           error: 'Input.insertText failed: ' + String((err && err.message) || err) });
    return;
  }
  await new Promise((resolve) => setTimeout(resolve, 300));
  send({ id: msg.id, ok: true,
         value: { success: true, tag: c.tag, mode: 'contenteditable' } });
}

// ---------------- Phase-B agent tools (screenshot/upload/pdf/input) -------
// Second batch of standard browser-bridge agent tools. Same
// transport as Phase A: element reads/writes go through evaluate snippets on
// the shared chrome.debugger session (@eN refs resolve via resolveElement +
// lastSnapshot); raster/PDF/keyboard/mouse/upload go through direct CDP
// commands (Page.captureScreenshot, Page.printToPDF, Input.dispatchMouseEvent,
// Input.dispatchKeyEvent/insertText, DOM.setFileInputFiles). Screenshots and
// PDFs reply base64 — the CLIENT writes the file (the extension cannot write
// arbitrary local paths by design); upload takes a local absolute path that
// the BROWSER process reads.

// Fire one CDP command on the managed session after ensureDebugger, with the
// dead-session reset both runtimeEvaluate and handleCdp use. Throws on error;
// the handlers let the outer handleMessage catch shape {ok:false, error}.
async function cdpSend(tabId, method, params) {
  const attachError = await ensureDebugger(tabId);
  if (attachError) throw new Error(attachError);
  try {
    return await sendCdp(tabId, method, params);
  } catch (err) {
    if (!err.dialogBlocking && debuggerTabId === tabId) {
      attachedTabs.delete(tabId);
      debuggerTabId = null;
      chrome.debugger.detach({ tabId }).catch(() => { /* noop */ });
    }
    throw err;
  }
}

// "navigate": the extended Phase-B action, kept in one place.
//   newTab absent/false (default): chrome.tabs.update(tabId?|active, {url});
//     reply is a bare {ok:true} — the pre-Phase-B wire shape, byte-compatible.
//     The debugger session stays attached and is never switched (see the
//     original inline comment this moved from: CDP sessions survive same-tab
//     navigation, so Runtime.evaluate keeps working on the new document; the
//     session is detached only when the WS closes, a different tab is
//     targeted via ensureDebugger, or the session dies (onDetach / command
//     failure)).
//   newTab:true: chrome.tabs.create({url, active:true}); when group_title is
//     given, chrome.tabs.group the new tab in its own window then
//     chrome.tabGroups.update the group's title. Reply {success:true, tabId,
//     groupId?}.
async function handleNavigate(msg) {
  const url = msg.url;
  if (typeof url !== 'string' || !url.trim()) throw new Error('missing url');
  if (msg.newTab === true) {
    const created = await chrome.tabs.create({ url, active: true });
    const value = { success: true, tabId: created.id };
    if (typeof msg.group_title === 'string' && msg.group_title.trim()) {
      const groupId = await chrome.tabs.group({
        tabIds: [created.id],
        createProperties: { windowId: created.windowId },
      });
      await chrome.tabGroups.update(groupId, { title: msg.group_title });
      value.groupId = groupId;
    }
    send({ id: msg.id, ok: true, value });
    return;
  }
  const tabId = await targetTabId(msg);
  let beforeUrl = '';
  try { beforeUrl = (await chrome.tabs.get(tabId)).url || ''; } catch (_) { /* noop */ }
  const downloadsBefore = downloadRecords.length;
  await chrome.tabs.update(tabId, { url });
  // P5: an attachment URL starts a DOWNLOAD and never commits a new document.
  // Give it a moment (bounded) so the Page.downloadWillBegin listener can
  // record it and the response can say what happened. A normal document
  // navigation commits a new tab url and ends this wait in tens of ms; only a
  // download actually waits the full 1000 ms. The reply VALUE is unchanged
  // ({"ok":true}); the feedback rides the additive top-level notice.
  const deadline = Date.now() + 1000;
  while (Date.now() < deadline && downloadRecords.length === downloadsBefore) {
    let tab;
    try { tab = await chrome.tabs.get(tabId); } catch (_) { break; }
    if (tab.url && tab.url !== beforeUrl) break;   // real navigation committed
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  send({ id: msg.id, ok: true });
}

// Shared "scroll into view then measure" snippet used by screenshot (clip
// rect) and mouse_click (element center). Runs page-side so rounding happens
// before CDP sees the numbers; x/y are clamped to the viewport origin for the
// clip case because an element LARGER than the viewport can legitimately poke
// out above/left of it after a center scroll.
function geometryExpression(sel, center) {
  return `(() => {
  try {
    const sel = ${JSON.stringify(sel)};
    const center = ${center ? 'true' : 'false'};
    const el = document.querySelector(sel);
    if (!el) return { error: "element not found: " + sel };
    if (typeof el.scrollIntoView === "function") {
      try { el.scrollIntoView({ block: "center", inline: "center" }); } catch (err) { /* noop */ }
    }
    const r = el.getBoundingClientRect();
    if (center && !r.width && !r.height) {
      return { error: "element has no layout box: " + sel };
    }
    if (center) {
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    }
    return {
      x: Math.max(0, Math.round(r.x)),
      y: Math.max(0, Math.round(r.y)),
      width: Math.max(1, Math.round(r.width)),
      height: Math.max(1, Math.round(r.height)),
    };
  } catch (err) {
    return { error: String((err && err.message) || err) };
  }
})()`;
}

// Read the pixel size out of a captured PNG/JPEG byte stream (base64).
// Page.captureScreenshot carries no width/height metadata besides the encoded
// image, so the reply size is decoded from the container headers: PNG IHDR
// (bytes 16-23) or the first JPEG SOFn marker. {width:null, height:null} when
// undecodable.
function decodeImageSize(base64, mime) {
  try {
    const bin = atob(base64);
    if (mime === 'image/png' && bin.length >= 24) {
      const width = ((bin.charCodeAt(16) * 256 + bin.charCodeAt(17)) * 65536 +
                     bin.charCodeAt(18) * 256 + bin.charCodeAt(19)) >>> 0;
      const height = ((bin.charCodeAt(20) * 256 + bin.charCodeAt(21)) * 65536 +
                      bin.charCodeAt(22) * 256 + bin.charCodeAt(23)) >>> 0;
      if (width && height) return { width, height };
    } else if (mime === 'image/jpeg') {
      let i = 2;                                 // skip SOI marker
      while (i + 9 <= bin.length) {
        if (bin.charCodeAt(i) !== 0xFF) { i += 1; continue; }
        const marker = bin.charCodeAt(i + 1);
        if (marker === 0xFF || marker === 0x00 || marker === 0xD8 ||
            marker === 0x01 || (marker >= 0xD0 && marker <= 0xD7)) {
          i += 2;
          continue;
        }
        if (marker === 0xD9 || marker === 0xDA) break;   // EOI/SOS: no SOF seen
        const len = bin.charCodeAt(i + 2) * 256 + bin.charCodeAt(i + 3);
        const isSof = (marker >= 0xC0 && marker <= 0xC3) ||
                      (marker >= 0xC5 && marker <= 0xC7) ||
                      (marker >= 0xC9 && marker <= 0xCB) ||
                      (marker >= 0xCD && marker <= 0xCF);
        if (isSof) {
          const height = bin.charCodeAt(i + 5) * 256 + bin.charCodeAt(i + 6);
          const width = bin.charCodeAt(i + 7) * 256 + bin.charCodeAt(i + 8);
          if (width && height) return { width, height };
        }
        i += 2 + len;
      }
    }
  } catch (_) { /* malformed base64 — fall through to nulls */ }
  return { width: null, height: null };
}

// "screenshot": Page.captureScreenshot on the active tab (or an explicit
// tabId). With a selector the element is scrolled into view and a clip of its
// bounding rect is captured; otherwise the visible viewport — or the whole
// page when fullPage:true. Reply value {base64, mime, width, height}; width /
// height are decoded from the captured bytes. Errors are explicit {ok:false,
// error}.
async function handleScreenshot(msg) {
  const tabId = await targetTabId(msg);
  await chrome.tabs.get(tabId);                // fail fast on stale tabIds
  const format = (typeof msg.format === 'string' && msg.format)
    ? msg.format.toLowerCase() : 'png';
  if (format !== 'png' && format !== 'jpeg') {
    throw new Error("format must be 'png' or 'jpeg'");
  }
  const mime = format === 'png' ? 'image/png' : 'image/jpeg';
  let quality;
  if (msg.quality !== undefined) {
    if (!Number.isInteger(msg.quality) || msg.quality < 0 || msg.quality > 100) {
      throw new Error('quality must be an integer 0-100');
    }
    if (format === 'png') throw new Error('quality applies to jpeg format only');
    quality = msg.quality;
  }
  const params = { format };
  if (quality !== undefined) params.quality = quality;

  if (typeof msg.selector === 'string' && msg.selector.trim()) {
    const path = resolveElement(tabId, msg.selector);
    const tab = await chrome.tabs.get(tabId);
    const geo = await evaluateOnTab(tab, geometryExpression(path, false));
    if (!geo.ok) throw new Error(geo.error);
    const g = geo.value || {};
    if (g.error) throw new Error(g.error);
    params.clip = {
      x: g.x,
      y: g.y,
      width: Math.max(1, Math.round(g.width)),
      height: Math.max(1, Math.round(g.height)),
      scale: 1,
    };
  } else if (msg.fullPage === true) {
    params.captureBeyondViewport = true;
  }

  const result = await cdpSend(tabId, 'Page.captureScreenshot', params);
  const data = (result && typeof result.data === 'string') ? result.data : '';
  if (!data) throw new Error('Page.captureScreenshot returned no image data');
  const size = decodeImageSize(data, mime);
  send({ id: msg.id, ok: true,
         value: { base64: data, mime,
                  width: size.width, height: size.height } });
}

// Classify the resolved upload target page-side: {tag, type} of the element
// behind the CSS path, so a non-file input fails with a precise message.
function fileInputExpression(sel) {
  return `(() => {
  try {
    const sel = ${JSON.stringify(sel)};
    const el = document.querySelector(sel);
    if (!el) return { error: "element not found: " + sel };
    return { tag: (el.tagName || "").toLowerCase(),
             type: (el.type || "").toLowerCase() };
  } catch (err) {
    return { error: String((err && err.message) || err) };
  }
})()`;
}

// "upload": set a LOCAL absolute path onto an <input type="file"> through
// the held debugger session's DOM domain, so the page receives a real File
// (the browser process reads the path — no base64). Steps: DOM.getDocument ->
// DOM.querySelector {selector} -> verify it is a file input (Runtime.evaluate
// read) -> DOM.setFileInputFiles {files:[path], nodeId}. Errors are explicit.
async function handleUpload(msg) {
  const file = msg.file;
  if (typeof file !== 'string' || !file.trim()) throw new Error('missing file path');
  const tabId = await targetTabId(msg);
  const path = resolveElement(tabId, msg.selector);   // CSS or @eN -> CSS path
  const tab = await chrome.tabs.get(tabId);

  const cls = await evaluateOnTab(tab, fileInputExpression(path));
  if (!cls.ok) throw new Error(cls.error);
  const c = cls.value || {};
  if (c.error) throw new Error(c.error);
  if (c.tag !== 'input' || c.type !== 'file') {
    throw new Error('selector does not match an <input type="file"> — got <' +
                    c.tag + (c.tag === 'input' ? ' type="' + (c.type || '') + '"' : '') +
                    '>');
  }

  const doc = await cdpSend(tabId, 'DOM.getDocument');
  const rootId = doc && doc.root && doc.root.nodeId;
  if (!rootId) throw new Error('DOM.getDocument returned no document root');
  const q = await cdpSend(tabId, 'DOM.querySelector',
                          { nodeId: rootId, selector: path });
  if (!q || !q.nodeId) throw new Error('input not found: ' + path);
  await cdpSend(tabId, 'DOM.setFileInputFiles',
                { files: [file], nodeId: q.nodeId });
  send({ id: msg.id, ok: true,
         value: { success: true, file, tag: 'input' } });
}

// "save_as_pdf": Page.printToPDF on the ACTIVE tab's session (printBackground
// on). Reply value {base64, mime:'application/pdf'} — the client writes the
// file.
async function handleSaveAsPdf(msg) {
  const tabId = await targetTabId(msg);
  await chrome.tabs.get(tabId);
  const result = await cdpSend(tabId, 'Page.printToPDF',
                               { printBackground: true });
  const data = (result && typeof result.data === 'string') ? result.data : '';
  if (!data) throw new Error('Page.printToPDF returned no data');
  send({ id: msg.id, ok: true,
         value: { base64: data, mime: 'application/pdf' } });
}

// "mouse_click": press + release the left button at viewport CSS pixels via
// Input.dispatchMouseEvent. A selector is scrolled into view and clicked at
// its element center; otherwise numeric x/y are required. Reply {success:true,
// x, y}.
async function handleMouseClick(msg) {
  const tabId = await targetTabId(msg);
  await chrome.tabs.get(tabId);                // fail fast on stale tabIds
  let x;
  let y;
  if (typeof msg.selector === 'string' && msg.selector.trim()) {
    const path = resolveElement(tabId, msg.selector);
    const tab = await chrome.tabs.get(tabId);
    const geo = await evaluateOnTab(tab, geometryExpression(path, true));
    if (!geo.ok) throw new Error(geo.error);
    const g = geo.value || {};
    if (g.error) throw new Error(g.error);
    x = g.x;
    y = g.y;
  } else {
    if (!Number.isInteger(msg.x) || !Number.isInteger(msg.y)) {
      throw new Error('mouse_click needs integer x/y coordinates or a selector');
    }
    x = msg.x;
    y = msg.y;
  }
  const event = { x, y, button: 'left', clickCount: 1 };
  await cdpSend(tabId, 'Input.dispatchMouseEvent',
                Object.assign({ type: 'mousePressed' }, event));
  if (msg.humanize === true) await humanizeDelay(30, 120);  // P1 jitter
  await cdpSend(tabId, 'Input.dispatchMouseEvent',
                Object.assign({ type: 'mouseReleased' }, event));
  send({ id: msg.id, ok: true, value: { success: true, x, y } });
}

// send_key key table: named keys + single characters. CDP
// Input.dispatchKeyEvent wants {key, code, windowsVirtualKeyCode}; single
// chars additionally carry `char` so the press can TYPE the character into a
// focused control. Windows VK codes follow the standard browser-bridge
// convention (Enter 13, Tab 9, ...
// ArrowUp 38, Space 32); letters use the upper-case char code, digits their
// own.
const NAMED_KEY_SPECS = {
  enter:      { key: 'Enter',     code: 'Enter',     vk: 13 },
  tab:        { key: 'Tab',       code: 'Tab',       vk: 9 },
  escape:     { key: 'Escape',    code: 'Escape',    vk: 27 },
  esc:        { key: 'Escape',    code: 'Escape',    vk: 27 },
  backspace:  { key: 'Backspace', code: 'Backspace', vk: 8 },
  delete:     { key: 'Delete',    code: 'Delete',    vk: 46 },
  arrowup:    { key: 'ArrowUp',   code: 'ArrowUp',   vk: 38 },
  arrowdown:  { key: 'ArrowDown', code: 'ArrowDown', vk: 40 },
  arrowleft:  { key: 'ArrowLeft', code: 'ArrowLeft', vk: 37 },
  arrowright: { key: 'ArrowRight', code: 'ArrowRight', vk: 39 },
  home:       { key: 'Home',      code: 'Home',      vk: 36 },
  end:        { key: 'End',       code: 'End',       vk: 35 },
  pageup:     { key: 'PageUp',    code: 'PageUp',    vk: 33 },
  pagedown:   { key: 'PageDown',  code: 'PageDown',  vk: 34 },
  space:      { key: ' ',         code: 'Space',     vk: 32 },
};

const SUPPORTED_KEYS_HINT =
  'Enter, Tab, Escape, Backspace, Delete, ArrowUp/Down/Left/Right, Home, ' +
  'End, PageUp, PageDown, Space, a-z, 0-9';

// Resolve a send_key argument to a CDP key spec ({key, code, vk, char?}) or
// null when unsupported. Named keys are matched case-insensitively; a literal
// ' ' is Space; single characters a-z/A-Z/0-9 are passed through as-is.
function keySpec(raw) {
  if (raw === ' ') return NAMED_KEY_SPECS.space;
  const named = NAMED_KEY_SPECS[raw.toLowerCase()];
  if (named) return named;
  if (/^[a-zA-Z0-9]$/.test(raw)) {
    const upper = raw.toUpperCase();
    return {
      key: raw,
      code: /^[0-9]$/.test(raw) ? 'Digit' + raw : 'Key' + upper,
      vk: /^[0-9]$/.test(raw) ? raw.charCodeAt(0) : upper.charCodeAt(0),
      char: raw,
    };
  }
  return null;
}

// modifiers string[] -> CDP modifiers bitmask (Alt=1, Ctrl=2, Meta=4,
// Shift=8). Throws on unknown names so callers learn the supported set.
function modifierBitmask(modifiers) {
  if (modifiers === undefined || modifiers === null) return 0;
  if (!Array.isArray(modifiers)) {
    throw new Error("modifiers must be an array, e.g. ['ctrl','shift']");
  }
  let bits = 0;
  for (const mod of modifiers) {
    const name = String(mod).toLowerCase();
    if (name === 'alt') bits |= 1;
    else if (name === 'ctrl' || name === 'control') bits |= 2;
    else if (name === 'meta') bits |= 4;
    else if (name === 'shift') bits |= 8;
    else throw new Error('unsupported modifier: ' + mod +
                         ' — supported: alt, ctrl, meta, shift');
  }
  return bits;
}

// "send_key": dispatch a keyDown + keyUp pair via Input.dispatchKeyEvent.
// Named keys use their Windows VK code; single characters type (text is set
// on the keyDown) unless ctrl/alt/meta is held — a modifier shortcut must not
// also insert the character (Ctrl+A selects; it does not type 'a'). Shift +
// lowercase letter capitalizes the typed character. Optional selector is
// focused first. Reply {success:true, key}.
async function handleSendKey(msg) {
  if (typeof msg.key !== 'string' || !msg.key.length) throw new Error('missing key');
  const spec = keySpec(msg.key);
  if (!spec) {
    throw new Error('unsupported key: ' + msg.key + ' — supported: ' +
                    SUPPORTED_KEYS_HINT);
  }
  const mods = modifierBitmask(msg.modifiers);
  const tabId = await targetTabId(msg);
  const tab = await chrome.tabs.get(tabId);

  if (typeof msg.selector === 'string' && msg.selector.trim()) {
    const path = resolveElement(tabId, msg.selector);
    const f = await evaluateOnTab(tab, focusExpression(path));
    if (!f.ok) throw new Error(f.error);
    const fv = f.value || {};
    if (fv.error) throw new Error(fv.error);
  }

  let key = spec.key;
  let text;
  if (typeof spec.char === 'string') {
    if ((mods & 8) && /^[a-z]$/.test(spec.char)) {    // shift + lowercase letter
      key = spec.char.toUpperCase();
      text = key;
    } else if (mods & (1 | 2 | 4)) {                  // ctrl/alt/meta shortcut
      text = undefined;
    } else {
      text = spec.char;
    }
  }

  const down = { type: 'keyDown', key, code: spec.code,
                 windowsVirtualKeyCode: spec.vk, modifiers: mods };
  const up = { type: 'keyUp', key, code: spec.code,
               windowsVirtualKeyCode: spec.vk, modifiers: mods };
  if (typeof text === 'string') down.text = text;
  await cdpSend(tabId, 'Input.dispatchKeyEvent', down);
  if (msg.humanize === true) await humanizeDelay(30, 120);  // P1 jitter
  await cdpSend(tabId, 'Input.dispatchKeyEvent', up);
  send({ id: msg.id, ok: true, value: { success: true, key } });
}

// "type_text": convenience typing — focus the selector first when given,
// then CDP Input.insertText inserts text at the caret (no per-key events, so
// it is the reliable path for CJK/emoji/paste-length text). Reply
// {success:true, len}.
async function handleTypeText(msg) {
  if (typeof msg.text !== 'string') throw new Error('missing text');
  const tabId = await targetTabId(msg);
  const tab = await chrome.tabs.get(tabId);
  if (typeof msg.selector === 'string' && msg.selector.trim()) {
    const path = resolveElement(tabId, msg.selector);
    const f = await evaluateOnTab(tab, focusExpression(path));
    if (!f.ok) throw new Error(f.error);
    const fv = f.value || {};
    if (fv.error) throw new Error(fv.error);
  }
  await cdpSend(tabId, 'Input.insertText', { text: msg.text });
  send({ id: msg.id, ok: true,
         value: { success: true, len: msg.text.length } });
}

// ---------------- P0 upgrade actions (submit/fill_form/wait_for/dialog/ -
// ---------------- drop/resize/network/console) ---------------------------
// New high-frequency agent actions. All element addressing keeps the CSS|@eN
// convention: @eN refs resolve through lastSnapshot (see resolveElement);
// raster/keyboard actions go through the shared cdpSend; page reads/writes go
// through evaluateOnTab snippets (IIFE — replMode-safe).

// "submit": requestSubmit on the form around the target (form itself, a form
// control, or a button inside one). Falls back to el.click() when no form /
// requestSubmit exists so a bare submit button still fires its handler.
function submitExpression(sel) {
  return `(() => {
  try {
    const sel = ${JSON.stringify(sel)};
    const el = document.querySelector(sel);
    if (!el) return { error: "element not found: " + sel };
    if (typeof el.scrollIntoView === "function") {
      try { el.scrollIntoView({ block: "center" }); } catch (err) { /* noop */ }
    }
    const tag = (el.tagName || "").toLowerCase();
    let form = null;
    if (tag === "form") form = el;
    else if (el.form) form = el.form;
    else if (typeof el.closest === "function") form = el.closest("form");
    if (form && typeof form.requestSubmit === "function") {
      form.requestSubmit();
      return { success: true, tag: tag, mode: "requestSubmit" };
    }
    el.click();
    return { success: true, tag: tag, mode: "click" };
  } catch (err) {
    return { error: String((err && err.message) || err) };
  }
})()`;
}

// "fill_form": fill many value-type controls (input/textarea/select) in ONE
// page pass (native value setter + input/change — React-safe). contenteditable
// fields are reported as errors (they need CDP Input.insertText; use fill with
// mode:"contenteditable" per field). value = {success, filled:[...],
// errors:[{selector,error}]} — a field error never aborts the other fields.
function fillFormExpression(fields) {
  return `(() => {
  const fields = ${JSON.stringify(fields)};
  const filled = [];
  const errors = [];
  function nativeSet(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value); else el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  for (const f of fields) {
    try {
      const el = document.querySelector(f.sel);
      if (!el) { errors.push({ selector: f.sel, error: "element not found" }); continue; }
      const tag = (el.tagName || "");   // keep UPPERCASE — compared to literals below
      if (tag === "SELECT") {
        el.value = f.value;
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else if (tag === "INPUT" || tag === "TEXTAREA") {
        nativeSet(el, f.value);
      } else if (el.isContentEditable || (el.getAttribute && (el.getAttribute("contenteditable") === "" || el.getAttribute("contenteditable") === "true" || el.getAttribute("contenteditable") === "plaintext-only"))) {
        errors.push({ selector: f.sel, error: 'contenteditable — fill it separately with mode:"contenteditable"' });
        continue;
      } else {
        errors.push({ selector: f.sel, error: "unsupported element <" + tag + ">" });
        continue;
      }
      filled.push(f.sel);
    } catch (err) {
      errors.push({ selector: f.sel, error: String((err && err.message) || err) });
    }
  }
  return { success: true, filled: filled, errors: errors };
})()`;
}

// wait_for check expressions. `until` is 'appear' (default — element exists
// and has a layout box), 'gone' (element removed from the DOM) or 'hidden'
// (no layout box: visibility:hidden / display:none). With text, appear also
// needs the text; hidden is satisfied by "element not visible OR text no
// longer present"; gone (selector is mandatory there) also requires the text
// to be gone when text is given. selector may be null (whole-document text
// scan). Every check is an IIFE returning a boolean — replMode-safe.
function buildWaitCheckExpression(css, text, until) {
  const mode = until || 'appear';
  const t = JSON.stringify(text);
  const cssJson = JSON.stringify(css);
  const elVisible = `(() => { try { const el = document.querySelector(${cssJson});
    if (!el) return false; const r = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
    return !!r && (r.width > 0 || r.height > 0); } catch (_) { return false; } })()`;
  const elGone = `(() => { try { return !document.querySelector(${cssJson}); } catch (_) { return false; } })()`;
  // No layout box, display:none or visibility:hidden => not visible.
  const elHidden = `(() => { try { const el = document.querySelector(${cssJson});
    if (!el) return true;
    const st = (typeof window.getComputedStyle === 'function') ? window.getComputedStyle(el) : null;
    if (st && (st.visibility === 'hidden' || st.display === 'none')) return true;
    const r = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
    return !r || (r.width === 0 && r.height === 0); } catch (_) { return false; } })()`;
  const textPresent = `(() => { const t = ${t};
    try { const all = document.querySelectorAll("body *");
      for (const el of all) {
        const r = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
        if (!r || (r.width === 0 && r.height === 0)) continue;
        const hay = ((el.innerText || "") + " " + (el.value !== undefined ? String(el.value) : ""));
        if (hay.indexOf(t) !== -1) return true;
      } } catch (_) { return false; } return false; })()`;
  if (mode === 'gone') {
    if (!text) return elGone;
    return `(() => (${elGone}) && !(${textPresent}))()`;
  }
  if (mode === 'hidden') {
    if (css && !text) return elHidden;
    if (!css) return `(() => !(${textPresent}))()`;
    return `(() => (${elHidden}) || !(${textPresent}))()`;
  }
  // appear (default) — unchanged from the pre-v1.4 behaviour.
  if (css && !text) return elVisible;
  if (css && text) {
    return `(() => { try { const el = document.querySelector(${cssJson});
      if (!el) return false; const r = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
      if (!r || (r.width === 0 && r.height === 0)) return false;
      const hay = ((el.innerText || "") + " " + (el.value !== undefined ? String(el.value) : ""));
      return hay.indexOf(${t}) !== -1; } catch (_) { return false; } })()`;
  }
  return textPresent;
}

// "drop": build a real File per item (name/mime/base64 data) in the page
// MAIN world and dispatch dragenter/dragover/drop onto the target element —
// the same DataTransfer path the publish scripts already use for image drops.
function dropExpression(sel, files) {
  return `(() => {
  try {
    const sel = ${JSON.stringify(sel)};
    const files = ${JSON.stringify(files)};
    const el = document.querySelector(sel);
    if (!el) return { error: "element not found: " + sel };
    if (typeof el.scrollIntoView === "function") {
      try { el.scrollIntoView({ block: "center" }); } catch (err) { /* noop */ }
    }
    const dt = new DataTransfer();
    for (const f of files) {
      const bin = atob(f.data);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
      const file = new File([bytes], f.name, { type: f.mime || "application/octet-stream" });
      dt.items.add(file);
    }
    const opts = { bubbles: true, cancelable: true, dataTransfer: dt };
    el.dispatchEvent(new DragEvent("dragenter", opts));
    el.dispatchEvent(new DragEvent("dragover", opts));
    el.dispatchEvent(new DragEvent("drop", opts));
    el.dispatchEvent(new DragEvent("dragleave", opts));
    return { success: true, dropped: files.length };
  } catch (err) {
    return { error: String((err && err.message) || err) };
  }
})()`;
}

// "submit" — see submitExpression.
async function handleSubmit(msg) {
  if (typeof msg.selector !== 'string' || !msg.selector.trim()) {
    throw new Error('submit needs a selector (form, control or submit button)');
  }
  const tabId = await targetTabId(msg);
  const path = resolveElement(tabId, msg.selector);
  const tab = await chrome.tabs.get(tabId);
  const r = await evaluateOnTab(tab, submitExpression(path));
  if (!r.ok) { send({ id: msg.id, ok: false, error: r.error }); return; }
  const v = r.value || {};
  if (v.error) { send({ id: msg.id, ok: false, error: v.error }); return; }
  send({ id: msg.id, ok: true, value: v });
}

// "fill_form" — batch fill, see fillFormExpression.
async function handleFillForm(msg) {
  const raw = msg.fields;
  if (!Array.isArray(raw) || !raw.length) {
    throw new Error("fill_form needs fields:[{selector,value}, ...]");
  }
  const tabId = await targetTabId(msg);
  const fields = [];
  for (const f of raw) {
    if (!f || typeof f.value !== 'string' ||
        typeof f.selector !== 'string' || !f.selector.trim()) {
      throw new Error('every field needs {selector (CSS|@eN), value (string)}');
    }
    fields.push({ sel: resolveElement(tabId, f.selector.trim()), value: f.value });
  }
  const tab = await chrome.tabs.get(tabId);
  const r = await evaluateOnTab(tab, fillFormExpression(fields));
  if (!r.ok) { send({ id: msg.id, ok: false, error: r.error }); return; }
  const v = r.value || {};
  if (v.error) { send({ id: msg.id, ok: false, error: v.error }); return; }
  send({ id: msg.id, ok: true, value: v });
}

// "wait_for" — poll until the target appears (and optionally contains text).
// v1.4: `until` selects appear|gone|hidden and `networkIdleMs` additionally
// waits for that many ms without a request/response event on this tab.
// Selector is resolved ONCE (CSS or @eN) and the check runs page-side every
// intervalMs; default timeout 10 s, max 90 s (daemon EVAL_TIMEOUT is 120 s).
async function handleWaitFor(msg) {
  const timeout = (Number.isInteger(msg.timeoutMs) && msg.timeoutMs > 0)
    ? Math.min(msg.timeoutMs, 90000) : 10000;
  const interval = (Number.isInteger(msg.intervalMs) && msg.intervalMs > 0)
    ? Math.min(msg.intervalMs, 2000) : 300;
  const until = (typeof msg.until === 'string' && msg.until) ? msg.until : 'appear';
  if (until !== 'appear' && until !== 'gone' && until !== 'hidden') {
    throw new Error("wait_for until must be 'appear', 'gone' or 'hidden'");
  }
  const networkIdleMs = (Number.isInteger(msg.networkIdleMs) && msg.networkIdleMs > 0)
    ? Math.min(msg.networkIdleMs, 30000) : null;
  const tabId = await targetTabId(msg);
  const tab = await chrome.tabs.get(tabId);

  let css = null;
  if (typeof msg.selector === 'string' && msg.selector.trim()) {
    css = resolveElement(tabId, msg.selector, msg.index);
  }
  const text = (typeof msg.text === 'string' && msg.text) ? msg.text : null;
  if (!css && !text) throw new Error('wait_for needs a selector and/or text');
  if (until === 'gone' && !css) {
    throw new Error("wait_for until='gone' needs a selector");
  }
  const check = buildWaitCheckExpression(css, text, until);
  const started = Date.now();
  for (;;) {
    const r = await evaluateOnTab(tab, check);
    if (!r.ok) { send({ id: msg.id, ok: false, error: r.error }); return; }
    const condOk = r.value === true;
    const idleFor = Date.now() - lastNetActivity;
    const netOk = networkIdleMs === null || idleFor >= networkIdleMs;
    if (condOk && netOk) {
      const value = { found: true, elapsedMs: Date.now() - started,
                      matched: until };
      if (networkIdleMs !== null) value.lastNetworkActivityMs = idleFor;
      send({ id: msg.id, ok: true, value: value });
      return;
    }
    if (Date.now() - started >= timeout) {
      const target = (css ? ' selector=' + css : '') +
                     (text ? ' text=' + JSON.stringify(text) : '');
      const reason = !condOk
        ? 'condition not met (until=' + until + target + ')'
        : 'condition met but the page was not network-idle for ' +
          networkIdleMs + 'ms (last activity ' + idleFor + 'ms ago)';
      send({ id: msg.id, ok: false,
             error: 'wait_for timed out after ' + timeout + 'ms: ' + reason });
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
}

// P1: default native-dialog handling. Called from the
// Page.javascriptDialogOpening listener; fire-and-forget. In 'auto-accept'
// mode it resolves the dialog with Page.handleJavaScriptDialog {accept:true}
// (beforeunload/alert/confirm/prompt alike) so the blocked page runs again
// without an explicit handle_dialog. A failure is NOT swallowed: it is sent
// to the daemon as an unsolicited notice (queryable via GET /status and
// carried on the next /command response) and the dialog stays pending for a
// manual handle_dialog retry.
async function autoHandleDialog(tabId, dialog) {
  if (dialogPolicy !== 'auto-accept') return;
  try {
    await sendCdp(tabId, 'Page.handleJavaScriptDialog', { accept: true });
    // Resolved at the browser layer: keep the state machine consistent with
    // the real browser (Page.javascriptDialogClosed will fire too).
    if (pendingDialog && pendingDialog.tabId === tabId &&
        pendingDialog.openedAt === dialog.openedAt) {
      pendingDialog = null;
    }
    if (lastDialogAutoError && lastDialogAutoError.tabId === tabId) {
      lastDialogAutoError = null;
    }
  } catch (err) {
    lastDialogAutoError = {
      tabId,
      type: dialog.type,
      message: dialog.message,
      url: dialog.url,
      error: String((err && err.message) || err),
      at: Date.now(),
    };
    // P1 (batch 2): an in-flight command is now hard-blocked by a dialog whose
    // auto-accept failed — fail it fast in the same action too.
    notifyDialogBlocked();
    notifyDaemon({
      kind: 'auto_dialog_failed',
      text: 'auto-accept of a native ' + dialog.type + ' dialog failed: ' +
            String((err && err.message) || err),
      dialog: {
        type: dialog.type,
        message: dialog.message,
        defaultPrompt: dialog.defaultPrompt,
        url: dialog.url,
      },
    });
  }
}

// "handle_dialog": accept/dismiss/answer the JavaScript dialog (alert/
// confirm/prompt/beforeunload) currently showing on the target tab.
//
// Chrome suppresses native dialogs while a debugger is attached: the page
// blocks on the dialog and the extension sees Page.javascriptDialogOpening
// (we enable the Page domain on attach). handleDialog waits up to timeoutMs
// (default 2000) for that event — the caller usually clicks the element that
// opens the dialog first — then resolves it via Page.handleJavaScriptDialog.
// accept defaults true (OK); promptText answers a prompt(). If the page never
// opened a dialog the wait times out with a clean {ok:false, error}.
//
// Since P1 the DEFAULT policy is auto-accept: the dialog is usually already
// resolved by the time a caller runs this action (which then reports "no
// JavaScript dialog is showing"). Set the policy to 'manual' (daemon
// --no-auto-dialog or the set_dialog_policy action) to make this action the
// only resolver again.
async function handleDialog(msg) {
  const tabId = await targetTabId(msg);
  await chrome.tabs.get(tabId);
  const accept = msg.accept !== false;
  const promptText = (typeof msg.promptText === 'string') ? msg.promptText : null;
  const timeoutMs = (Number.isInteger(msg.timeoutMs) && msg.timeoutMs > 0)
    ? Math.min(msg.timeoutMs, 15000) : 2000;

  // Make sure the debugger session is live. (Page.enable is already done on
  // attach by enableCollectorDomains; re-enabling here is both unnecessary and
  // deadly while a dialog is pending, since Page.enable needs the page's main
  // thread to answer and the dialog blocks it — Page.handleJavaScriptDialog is
  // handled at the browser layer and returns immediately.)
  const attachError = await ensureDebugger(tabId);
  if (attachError) throw new Error(attachError);

  const deadline = Date.now() + timeoutMs;
  // Wait for a dialog on the TARGET tab only; another tab's dialog is not
  // ours to resolve (and must not be reported as a success here).
  while (!(pendingDialog && pendingDialog.tabId === tabId) && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 50));
  }
  const params = { accept };
  if (promptText !== null) params.promptText = promptText;

  const dialog = (pendingDialog && pendingDialog.tabId === tabId)
    ? pendingDialog : null;
  if (!dialog) {
    // P1/P2 (batch 2): a dialog that predates our attach never fires
    // Page.javascriptDialogOpening (the frozen renderer cannot report it), so
    // pendingDialog stays empty. After a recent CDP timeout we know the page
    // was blocked, and Page.handleJavaScriptDialog is browser-level: try it
    // once so this action also works on the attach-before-dialog boundary.
    const recentlyBlocked = debuggerBlocked &&
      debuggerBlocked.tabId === tabId &&
      (Date.now() - debuggerBlocked.at < 120000);
    if (recentlyBlocked) {
      try {
        await sendCdp(tabId, 'Page.handleJavaScriptDialog', params);
        if (pendingDialog && pendingDialog.tabId === tabId) pendingDialog = null;
        if (lastDialogAutoError && lastDialogAutoError.tabId === tabId) {
          lastDialogAutoError = null;
        }
        debuggerBlocked = null;
        send({ id: msg.id, ok: true, value: {
          success: true, dialog: null, accept, promptText,
          note: 'resolved a dialog that opened before the debugger attached',
        } });
        return;
      } catch (_) { /* fall through to the clean no-dialog error */ }
    }
    send({ id: msg.id, ok: false,
           error: `no JavaScript dialog is showing within ${timeoutMs}ms` });
    return;
  }
  try {
    await sendCdp(tabId, 'Page.handleJavaScriptDialog', params);
  } catch (err) {
    send({ id: msg.id, ok: false,
           error: String((err && err.message) || err) });
    return;
  }
  // Page.javascriptDialogClosed also clears it; scope the local clear too.
  if (pendingDialog && pendingDialog.tabId === tabId) pendingDialog = null;
  if (lastDialogAutoError && lastDialogAutoError.tabId === tabId) {
    lastDialogAutoError = null;
  }
  send({
    id: msg.id, ok: true,
    value: {
      success: true,
      dialog: {
        type: dialog.type,
        message: dialog.message,
        defaultPrompt: dialog.defaultPrompt,
      },
      accept,
      promptText,
    },
  });
}

// "set_dialog_policy": switch native-dialog handling at runtime. No browser
// action is needed (works even while a dialog is blocking the page), so this
// is intentionally NOT routed through the debugger. The daemon owns the
// default (--no-auto-dialog) and pushes the same value on connect.
function handleSetDialogPolicy(msg) {
  const policy = msg.policy;
  if (policy !== 'auto-accept' && policy !== 'manual') {
    send({ id: msg.id, ok: false,
           error: "policy must be 'auto-accept' or 'manual'" });
    return;
  }
  dialogPolicy = policy;
  send({ id: msg.id, ok: true, value: { policy: dialogPolicy } });
}

// "list_downloads": newest-first record of downloads triggered by controlled
// actions (P5). No browser action: reads the in-memory ring the
// Page.downloadWillBegin listener fills, so it answers even while a page is
// blocked. `limit` (positive integer) caps the list.
async function handleListDownloads(msg) {
  const limit = (Number.isInteger(msg.limit) && msg.limit > 0)
    ? Math.min(msg.limit, downloadRecords.length) : downloadRecords.length;
  const newestFirst = downloadRecords.slice().reverse().slice(0, limit);
  send({ id: msg.id, ok: true,
         value: { downloads: newestFirst, count: downloadRecords.length } });
}

// "handle_file_chooser": programmatically answer a native file chooser that
// Page.setInterceptFileChooserDialog {enabled:true} (sent on every attach by
// enableCollectorDomains) intercepted — clicking ANY file input or a custom
// upload control that opens a chooser fires Page.fileChooserOpened instead of
// showing the native UI, and we record it in pendingFileChooser. This action
// waits up to timeoutMs (default 3000) for that event — the caller usually
// clicks / navigates to the control first — then puts a LOCAL absolute path
// onto the chooser's input node. The backendNodeId variant of
// DOM.setFileInputFiles is used (not nodeId — no DOM.getDocument/querySelector
// round-trip needed; the BROWSER process reads the path, no base64). A CDP
// failure (e.g. the file path does not exist) is passed through verbatim.
async function handleFileChooser(msg) {
  const file = msg.file;
  if (typeof file !== 'string' || !file.trim()) throw new Error('missing file path');
  const tabId = await targetTabId(msg);
  await chrome.tabs.get(tabId);                // fail fast on stale tabIds
  const timeoutMs = (Number.isInteger(msg.timeoutMs) && msg.timeoutMs > 0)
    ? Math.min(msg.timeoutMs, 15000) : 3000;

  // Make sure the debugger session is live. (setInterceptFileChooserDialog is
  // already enabled on attach by enableCollectorDomains; re-sending is
  // unnecessary.)
  const attachError = await ensureDebugger(tabId);
  if (attachError) throw new Error(attachError);

  const deadline = Date.now() + timeoutMs;
  while (!pendingFileChooser && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 50));
  }
  const chooser = pendingFileChooser;
  if (!chooser) {
    send({ id: msg.id, ok: false,
           error: `no file chooser is open within ${timeoutMs}ms` });
    return;
  }
  try {
    await sendCdp(tabId, 'DOM.setFileInputFiles', {
      files: [file],
      backendNodeId: chooser.backendNodeId,
    });
  } catch (err) {
    send({ id: msg.id, ok: false,
           error: String((err && err.message) || err) });
    return;
  }
  pendingFileChooser = null;   // Page.fileChooserOpened is a one-shot event
  send({ id: msg.id, ok: true,
         value: { success: true, file, mode: chooser.mode } });
}

// "drop": drag local files (name/mime/base64, supplied by the daemon which
// read them from disk) onto the target drop zone. See dropExpression.
async function handleDrop(msg) {
  if (typeof msg.selector !== 'string' || !msg.selector.trim()) {
    throw new Error('drop needs a selector (the drop-zone element)');
  }
  const files = Array.isArray(msg.files) ? msg.files : [];
  if (!files.length) {
    throw new Error('drop needs files:[{name,mime,data(base64)}] — files are read by the daemon');
  }
  const tabId = await targetTabId(msg);
  const path = resolveElement(tabId, msg.selector);
  const tab = await chrome.tabs.get(tabId);
  const r = await evaluateOnTab(tab, dropExpression(path, files));
  if (!r.ok) { send({ id: msg.id, ok: false, error: r.error }); return; }
  const v = r.value || {};
  if (v.error) { send({ id: msg.id, ok: false, error: v.error }); return; }
  send({ id: msg.id, ok: true, value: v });
}

// "resize_page": set the page viewport via Emulation.setDeviceMetricsOverride
// (deviceScaleFactor 0 keeps the natural DPR). No reset action: call again
// with the real size to restore, or reload the page.
async function handleResizePage(msg) {
  if (!Number.isInteger(msg.width) || !Number.isInteger(msg.height) ||
      msg.width <= 0 || msg.height <= 0) {
    throw new Error('resize_page needs positive integer width and height');
  }
  const tabId = await targetTabId(msg);
  await chrome.tabs.get(tabId);
  await cdpSend(tabId, 'Emulation.setDeviceMetricsOverride', {
    width: msg.width, height: msg.height, deviceScaleFactor: 0, mobile: false,
  });
  send({ id: msg.id, ok: true,
         value: { success: true, width: msg.width, height: msg.height } });
}

// "list_network_requests" / "get_network_request" / "list_console_messages":
// read the CDP event collectors above (current session's tab, newest first).
function eventLimit(msg) {
  return (Number.isInteger(msg.limit) && msg.limit > 0)
    ? Math.min(msg.limit, EVENT_CAP) : EVENT_CAP;
}

async function handleListNetworkRequests(msg) {
  const requests = netEvents.slice(-eventLimit(msg)).reverse();
  send({ id: msg.id, ok: true, value: { requests } });
}

async function handleGetNetworkRequest(msg) {
  const rid = (typeof msg.requestId === 'string' && msg.requestId)
    ? msg.requestId : null;
  if (!rid) {
    throw new Error("get_network_request needs 'requestId' (string) — see list_network_requests");
  }
  const rec = netEvents.find((e) => e.requestId === rid) || null;
  send({ id: msg.id, ok: true, value: { found: !!rec, request: rec } });
}

async function handleListConsoleMessages(msg) {
  const messages = consoleEvents.slice(-eventLimit(msg)).reverse();
  send({ id: msg.id, ok: true, value: { messages } });
}

// ---------------- probe (diagnostic JS-injection path matrix) -------------

// Runs the probe snippet through the injection paths that survive current
// Chrome and replies {id, ok:true, value:{tab, paths}}; each path is captured
// independently as {ok, value|error} so a single failure never aborts the
// others.
//
// Removed from the matrix: P1a (content-script eval — the content script no
// longer exists; MV3 hardcodes a CSP into isolated worlds that forbids
// eval/new Function) and P2/P3 (executeScript 'code' strings — removed from
// the API; only 'files' and 'func' are accepted). Kept but now answering
// {ok:false, error:'unavailable: ...'} because the manifest no longer requests
// the "scripting" permission: P4/P6 (executeScript func in MAIN/ISOLATED
// worlds) and P5 (a func that new Function()s the snippet in the MAIN world).
// The one path that actually drives tabs is P7 (CDP Runtime.evaluate through
// the SHARED session manager above — it does not attach/detach per call and
// leaves the session in the same managed state as evaluate); it does not use
// the "scripting" permission and is unaffected.

function probeObject() {
  return { url: location.href, title: document.title, probe: 1 + 1 };
}

async function handleProbe(msg) {
  let tab;
  try {
    tab = await activeTab();
  } catch (err) {
    send({ id: msg.id, ok: false, error: String((err && err.message) || err) });
    return;
  }
  const code = (typeof msg.code === 'string' && msg.code.trim())
    ? msg.code
    : DEFAULT_PROBE_CODE;

  // tab.url/title come from the tabs API, never from evaluation.
  const tabInfo = { id: tab.id, url: tab.url, title: tab.title };
  if (!tab.url) {
    tabInfo.pageCspNote =
      'tab.url is not exposed to this extension; interpret MAIN-world results with care';
  } else if (!/^https?:/i.test(tab.url)) {
    tabInfo.pageCspNote =
      'non-http(s) page: MAIN-world results are not representative of normal web pages';
  }

  const paths = {};

  // P3 (batch 2): while a native dialog blocks the tab EVERY injection path
  // (chrome.scripting.executeScript included) waits on the frozen renderer, so
  // the probe would hang behind the same block it is meant to report. Answer
  // immediately with the dialog introspection and mark the skipped paths.
  const dialogBlock = nativeDialogBlockError(tab.id) ||
    probeDebuggerBlockedError(tab.id);
  if (dialogBlock) {
    const skipped = {
      ok: false,
      error: 'skipped: ' + dialogBlock.message,
    };
    for (const name of ['P4_executeScript_func_MAIN',
                        'P5_executeScript_func_eval_MAIN',
                        'P6_executeScript_func_ISOLATED',
                        'P7_chromeDebugger_evaluate']) {
      paths[name] = Object.assign({}, skipped);
    }
    send({ id: msg.id, ok: true, value: {
      tab: tabInfo,
      paths,
      dialog: { policy: dialogPolicy, pending: pendingDialog || null,
                lastError: lastDialogAutoError, blocking: true },
      downloads: { count: downloadRecords.length, last: lastDownload },
    } });
    return;
  }

  // P4-P6 — chrome.scripting.executeScript func-based paths. The manifest no
  // longer requests the "scripting" permission (nor any website host
  // permission): they are not needed to drive the user's tabs — that is
  // chrome.debugger's job (P7) — and the store rejects permissions the single
  // purpose does not require. The three paths stay in the matrix and answer
  // honestly instead of vanishing, so the shape of the probe reply is
  // unchanged.
  const scriptingUnavailable = {
    ok: false,
    error: "unavailable: the extension does not request the 'scripting' permission",
  };
  paths['P4_executeScript_func_MAIN'] = Object.assign({}, scriptingUnavailable);
  paths['P5_executeScript_func_eval_MAIN'] = Object.assign({}, scriptingUnavailable);
  paths['P6_executeScript_func_ISOLATED'] = Object.assign({}, scriptingUnavailable);

  // P7 — chrome.debugger (CDP) Runtime.evaluate, the same channel DevTools'
  // console uses. It runs in the page's MAIN world and is NOT subject to page
  // CSP or the isolated-world CSP, so arbitrary-string evaluation survives on
  // strict-CSP pages (x.com) where the other paths cannot. Reuses the shared
  // ensureDebugger session manager — no per-call attach/detach, and the
  // session is left attached (same managed state the evaluate action keeps).
  // Only ONE debugger may own a target: if DevTools is open on the tab,
  // ensureDebugger returns a busy error and that becomes the path error.
  await probePath(paths, 'P7_chromeDebugger_evaluate',
    () => debuggerEvaluateResult(tab.id, code));

  send({ id: msg.id, ok: true, value: {
    tab: tabInfo,
    paths,
    // P1/P5 introspection: no debugger action needed (the probe's own P7 path
    // is what blocks while a native dialog is pending).
    dialog: { policy: dialogPolicy, pending: pendingDialog || null,
              lastError: lastDialogAutoError, blocking: false },
    downloads: { count: downloadRecords.length, last: lastDownload },
  } });
}

// P3 (batch 2): a recent CDP timeout means the managed session is (or was just)
// blocked, so probe should skip the debugger paths rather than hang behind the
// same block. Short-lived: a later successful command clears debuggerBlocked.
function probeDebuggerBlockedError(tabId) {
  if (!debuggerBlocked || debuggerBlocked.tabId !== tabId) return null;
  if (Date.now() - debuggerBlocked.at > 60000) return null;
  return new Error(debuggerBlocked.method + ' did not respond recently (' +
                   debuggerBlocked.error + '); the debugger session may be ' +
                   'blocked by a native dialog or credential prompt');
}

// Run one probe path and record {ok:true, value} or {ok:false, error}; never
// throws, so one failing path cannot abort the matrix.
async function probePath(paths, name, fn) {
  try {
    paths[name] = { ok: true, value: jsonSafe(await fn()) };
  } catch (err) {
    paths[name] = { ok: false, error: String((err && err.message) || err) };
  }
}

// CDP (chrome.debugger) Runtime.evaluate through the shared session manager:
// ensureDebugger (attach if needed, reuse the live session otherwise), then
// extract the JSON-safe completion value. Does NOT detach when done — the
// session stays in the same managed state the evaluate action maintains.
async function debuggerEvaluateResult(tabId, code) {
  const attachError = await ensureDebugger(tabId);
  if (attachError) throw new Error(attachError);

  const resp = await runtimeEvaluate(tabId, code);

  if (resp.exceptionDetails) {
    throw new Error(JSON.stringify(resp.exceptionDetails).slice(0, 500));
  }
  const result = resp.result || {};           // CDP RemoteObject
  if (result.value !== undefined || result.type === 'object') {
    // Normal case: returnByValue puts the JSON-safe payload in .value.
    return result.value;
  }
  // Fallback: keep only the small JSON-safe RemoteObject marker ({type, ...});
  // never hand a raw CDP RemoteObject out as the value. jsonSafe normalizes
  // it again before the WS send.
  return { type: result.type };
}

// Keep path values strict-JSON-safe across the WS boundary (undefined -> null).
function jsonSafe(value) {
  if (value === undefined) return null;
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (err) {
    return { __jsonError: String((err && err.message) || err) };
  }
}

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs || !tabs.length) throw new Error('no active tab found');
  return tabs[0];
}

// ---------------- keep service worker alive ----------------
// MV3 suspends idle service workers after ~30 s; the periodic heartbeat timer
// (and any inbound WS frame) resets the idle timer so the socket stays usable.
// Timers do NOT survive a suspension, so the chrome.alarms watchdog below
// covers that case: the alarm fires even while this worker is suspended,
// wakes it, and force-reconnects if the daemon socket died while asleep.

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== 'webflow-reconnect') return;
  await suspendStateReady;    // persisted pause flag before deciding
  if (suspended) return;      // user paused the link: watchdog stays quiet
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    backoff = 1000;
    connect();              // connect() clears any pending reconnectTimer too
  }
});

connect();
// Arm the reconnect watchdog (0.5 min period — Chrome's unpacked minimum; the
// alarm fires on schedule even if this service worker has been suspended).
chrome.alarms.create('webflow-reconnect', { periodInMinutes: 0.5 });
