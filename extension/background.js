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
// A chrome.alarms watchdog ('rhino-reconnect', 0.5 min period) is the
// fallback for MV3 worker suspension: timers die with the worker, but the
// alarm still fires on the next wake-up and force-reconnects a dead socket.

const WS_URL = 'ws://127.0.0.1:10087';
const MAX_BACKOFF_MS = 30000;   // reconnect backoff cap (spec)
const HEARTBEAT_MS = 15000;     // < 30 s MV3 idle limit
const DEBUGGER_VERSION = '1.3'; // chrome.debugger protocol version

const DEFAULT_PROBE_CODE =
  "(() => ({ url: location.href, title: document.title, probe: 1 + 1 }))()";

let ws = null;
let backoff = 1000;             // 1s -> 2s -> 4s -> ... -> 30s
let reconnectTimer = null;
let heartbeatTimer = null;

// ---------------- debugger session state ----------------

let debuggerTabId = null;       // tab owning the live chrome.debugger session

// The browser ends our session on its own (tab closed, navigated somewhere
// non-debuggable, DevTools took over, renderer gone, ...). Null the state so
// the next evaluate attaches a fresh session instead of reusing a dead one.
chrome.debugger.onDetach.addListener((source, reason) => {
  if (source && typeof source.tabId === 'number' && source.tabId === debuggerTabId) {
    console.warn('[web-flow] debugger session ended on tab',
                 source.tabId, 'reason:', reason);
    debuggerTabId = null;
    pendingDialog = null;
    pendingFileChooser = null;
  }
});

// ---------------- socket management ----------------

function connect() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  try {
    ws = new WebSocket(WS_URL);
  } catch (err) {
    scheduleReconnect();
    return;
  }
  ws.onopen = () => {
    backoff = 1000;
    startHeartbeat();
    console.log('[web-flow] connected to daemon', WS_URL);
  };
  ws.onmessage = (ev) => { handleMessage(ev); };
  ws.onclose = () => {
    console.warn('[web-flow] daemon connection closed; retrying');
    stopHeartbeat();
    ws = null;
    scheduleReconnect();
    cleanupDebuggerSession();   // nothing to serve while the daemon is gone
  };
  ws.onerror = () => {                       // onerror is followed by onclose
    try { ws.close(); } catch (_) { /* noop */ }
  };
}

function scheduleReconnect() {
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

// ---------------- chrome.debugger session manager ----------------

// Detach whatever session we hold (used when targeting a different tab or
// shutting down). Swallows errors: detaching an already-dead session is fine.
async function detachDebugger(tabId) {
  try { await chrome.debugger.detach({ tabId }); } catch (_) { /* noop */ }
  if (debuggerTabId === tabId) debuggerTabId = null;
}

function cleanupDebuggerSession() {
  const tid = debuggerTabId;
  debuggerTabId = null;
  if (tid != null) {
    chrome.debugger.detach({ tabId: tid }).catch(() => { /* noop */ });
  }
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
  if (debuggerTabId != null) {
    await detachDebugger(debuggerTabId);      // switch to the newly targeted tab
  }
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await chrome.debugger.attach({ tabId }, DEBUGGER_VERSION);
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
             'http(s) site; chrome:// and Web Store pages cannot be debugged)';
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

// JS-dialog state machine (Page domain). Chrome auto-dismisses dialogs while
// a debugger is attached UNLESS something listens for the opening event and
// resolves them via Page.handleJavaScriptDialog. We keep the latest opening
// here so the handle_dialog action can accept/dismiss/answer it. While an
// entry is pending the page script is blocked on the dialog, so handle_dialog
// must always resolve it (see handleDialog) or the tab hangs.
let pendingDialog = null;  // {type,message,defaultPrompt,url,hasBrowserHandler} | null

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
  // Page.enable makes JS dialogs (alert/confirm/prompt/beforeunload) surface
  // as Page.javascriptDialogOpening events instead of Chrome auto-dismissing
  // them while a debugger is attached (see handleDialog below).
  for (const method of ['Network.enable', 'Runtime.enable', 'Page.enable']) {
    try { await chrome.debugger.sendCommand({ tabId }, method); }
    catch (_) { /* collectors are best-effort */ }
  }
  // Intercept native file-chooser dialogs: any file input (or custom upload
  // control that opens one) then fires Page.fileChooserOpened instead of
  // showing the OS dialog (see handleFileChooser). Idempotent; re-sent on
  // every fresh attach.
  try {
    await chrome.debugger.sendCommand({ tabId }, 'Page.setInterceptFileChooserDialog',
                                      { enabled: true });
  } catch (_) { /* best-effort, same as the collectors */ }
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (!source || source.tabId !== debuggerTabId) return;   // only our session
  if (!params || typeof params !== 'object') return;
  try {
    if (method === 'Network.requestWillBeSent') {
      const req = params.request || {};
      const url = typeof req.url === 'string' ? req.url : '';
      if (!/^https?:/i.test(url)) return;   // skip chrome-extension:// data: noise
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
      // opening — the page can only block on one dialog at a time.
      pendingDialog = {
        type: String(params.type || 'alert'),
        message: typeof params.message === 'string' ? params.message : '',
        defaultPrompt: typeof params.defaultPrompt === 'string' ? params.defaultPrompt : '',
        url: typeof params.url === 'string' ? params.url : '',
        hasBrowserHandler: !!params.hasBrowserHandler,
        openedAt: Date.now(),
      };
    } else if (method === 'Page.javascriptDialogClosed') {
      pendingDialog = null;
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
    return await chrome.debugger.sendCommand({ tabId }, 'Runtime.evaluate', {
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
    if (debuggerTabId === tabId) {
      debuggerTabId = null;
      chrome.debugger.detach({ tabId }).catch(() => { /* noop */ });
    }
    throw err;
  }
}

// ---------------- popup runtime messages ----------------
// The toolbar popup (popup.html) talks to this service worker over
// chrome.runtime messages — no daemon WebSocket is involved:
//   {type: "wf-ping"}              -> {ok:true, version, daemon: "connected"|"disconnected"}
//   {type: "wf-evaluate", code}    -> {ok:true, value} | {ok:false, error}
//        (active tab; routed through the SHARED debugger session helpers
//         below — ensureDebugger + runtimeEvaluate — never re-implemented)
// Every branch resolves a reply, so the listener never throws uncaught.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg !== 'object') return;

  if (msg.type === 'wf-ping') {
    sendResponse({
      ok: true,
      version: chrome.runtime.getManifest().version,
      daemon: (ws && ws.readyState === WebSocket.OPEN) ? 'connected' : 'disconnected',
    });
    return;
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
  if (!msg || typeof msg !== 'object' || !msg.id) return;   // ping etc.

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
  const attachError = await ensureDebugger(tab.id);
  if (attachError) return { ok: false, error: attachError };

  let resp;
  try {
    resp = await runtimeEvaluate(tab.id, code);
  } catch (err) {
    return { ok: false, error: String((err && err.message) || err) };
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

async function handleEvaluate(msg) {
  if (typeof msg.code !== 'string') throw new Error('missing code');
  // An explicit tabId targets that tab: chrome.tabs.get resolves it (and
  // throws when the tab is gone -> {ok:false, error}). Without one the ACTIVE
  // tab is used, exactly as before.
  const tab = (typeof msg.tabId === 'number')
    ? await chrome.tabs.get(msg.tabId)
    : await activeTab();
  const result = await evaluateOnTab(tab, msg.code);
  if (result.ok) send({ id: msg.id, ok: true, value: result.value });
  else send({ id: msg.id, ok: false, error: result.error });
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
    result = await chrome.debugger.sendCommand({ tabId }, method, params);
  } catch (err) {
    // Transport-level rejection while we believed the session was live means
    // the session died — reset it (same logic runtimeEvaluate uses) so the
    // next command attaches a fresh one, then report the failure.
    if (debuggerTabId === tabId) {
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
// Phase-A agent tools with OFFICIAL Kimi WebBridge-compatible names. Every
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
    await chrome.debugger.sendCommand({ tabId }, 'Input.insertText',
                                      { text: msg.value });
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
// Second batch of official Kimi WebBridge-compatible agent tools. Same
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
    return await chrome.debugger.sendCommand({ tabId }, method, params || {});
  } catch (err) {
    if (debuggerTabId === tabId) {
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
  await chrome.tabs.update(tabId, { url });
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
  await cdpSend(tabId, 'Input.dispatchMouseEvent',
                Object.assign({ type: 'mouseReleased' }, event));
  send({ id: msg.id, ok: true, value: { success: true, x, y } });
}

// send_key key table: named keys + single characters. CDP
// Input.dispatchKeyEvent wants {key, code, windowsVirtualKeyCode}; single
// chars additionally carry `char` so the press can TYPE the character into a
// focused control. Windows VK codes follow the Kimi spec (Enter 13, Tab 9, ...
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

// wait_for check expressions: element exists AND has a layout box; with text,
// innerText/value must contain it. selector may be null (whole-document text
// scan). Every check is an IIFE returning a boolean — replMode-safe.
function buildWaitCheckExpression(css, text) {
  const t = JSON.stringify(text);
  if (css && !text) {
    return `(() => { try { const el = document.querySelector(${JSON.stringify(css)});
      if (!el) return false; const r = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
      return !!r && (r.width > 0 || r.height > 0); } catch (_) { return false; } })()`;
  }
  if (css && text) {
    return `(() => { try { const el = document.querySelector(${JSON.stringify(css)});
      if (!el) return false; const r = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
      if (!r || (r.width === 0 && r.height === 0)) return false;
      const hay = ((el.innerText || "") + " " + (el.value !== undefined ? String(el.value) : ""));
      return hay.indexOf(${t}) !== -1; } catch (_) { return false; } })()`;
  }
  return `(() => { const t = ${t};
    try { const all = document.querySelectorAll("body *");
      for (const el of all) {
        const r = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
        if (!r || (r.width === 0 && r.height === 0)) continue;
        const hay = ((el.innerText || "") + " " + (el.value !== undefined ? String(el.value) : ""));
        if (hay.indexOf(t) !== -1) return true;
      } } catch (_) { return false; } return false; })()`;
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
// Selector is resolved ONCE (CSS or @eN) and the check runs page-side every
// intervalMs; default timeout 10 s, max 90 s (daemon EVAL_TIMEOUT is 120 s).
async function handleWaitFor(msg) {
  const timeout = (Number.isInteger(msg.timeoutMs) && msg.timeoutMs > 0)
    ? Math.min(msg.timeoutMs, 90000) : 10000;
  const interval = (Number.isInteger(msg.intervalMs) && msg.intervalMs > 0)
    ? Math.min(msg.intervalMs, 2000) : 300;
  const tabId = await targetTabId(msg);
  const tab = await chrome.tabs.get(tabId);

  let css = null;
  if (typeof msg.selector === 'string' && msg.selector.trim()) {
    css = resolveElement(tabId, msg.selector, msg.index);
  }
  const text = (typeof msg.text === 'string' && msg.text) ? msg.text : null;
  if (!css && !text) throw new Error('wait_for needs a selector and/or text');
  const check = buildWaitCheckExpression(css, text);
  const started = Date.now();
  for (;;) {
    const r = await evaluateOnTab(tab, check);
    if (!r.ok) { send({ id: msg.id, ok: false, error: r.error }); return; }
    if (r.value === true) {
      send({ id: msg.id, ok: true,
             value: { found: true, elapsedMs: Date.now() - started } });
      return;
    }
    if (Date.now() - started >= timeout) {
      send({ id: msg.id, ok: false,
             error: 'wait_for timed out after ' + timeout + 'ms' +
                    (css ? ' selector=' + css : '') +
                    (text ? ' text=' + JSON.stringify(text) : '') });
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, interval));
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
  while (!pendingDialog && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 50));
  }
  const dialog = pendingDialog;
  if (!dialog) {
    send({ id: msg.id, ok: false,
           error: `no JavaScript dialog is showing within ${timeoutMs}ms` });
    return;
  }
  const params = { accept };
  if (promptText !== null) params.promptText = promptText;
  try {
    await chrome.debugger.sendCommand({ tabId }, 'Page.handleJavaScriptDialog', params);
  } catch (err) {
    send({ id: msg.id, ok: false,
           error: String((err && err.message) || err) });
    return;
  }
  pendingDialog = null;   // Page.javascriptDialogClosed also clears it
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
    await chrome.debugger.sendCommand({ tabId }, 'DOM.setFileInputFiles', {
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
// the API; only 'files' and 'func' are accepted). Kept: P4/P6 (executeScript
// func in MAIN/ISOLATED worlds), P5 (a func that new Function()s the snippet
// in the MAIN world — page CSP blocks it on strict sites, which is exactly
// why the evaluate action uses chrome.debugger), and P7 (CDP Runtime.evaluate
// through the SHARED session manager above — it does not attach/detach per
// call and leaves the session in the same managed state as evaluate).

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

  // P4-P6 — chrome.scripting.executeScript func-based paths (needs
  // "scripting" + host permissions; both are declared in manifest.json).
  await probePath(paths, 'P4_executeScript_func_MAIN',
    () => executeScriptResult({ target: { tabId: tab.id }, world: 'MAIN', func: probeObject }));
  await probePath(paths, 'P5_executeScript_func_eval_MAIN',
    () => executeScriptResult({
      target: { tabId: tab.id }, world: 'MAIN',
      func: (c) => { const f = new Function('return (' + c + ')'); return f(); },
      args: [code],
    }));
  await probePath(paths, 'P6_executeScript_func_ISOLATED',
    () => executeScriptResult({ target: { tabId: tab.id }, world: 'ISOLATED', func: probeObject }));

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

  send({ id: msg.id, ok: true, value: { tab: tabInfo, paths } });
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

// executeScript resolves to an array of per-frame InjectionResults; the
// snippet's completion value is result[0].result. Some failures surface as a
// resolved result object carrying an 'error' key rather than a rejection; a
// rejected promise (CSP / permission / runtime.lastError) becomes a throw.
async function executeScriptResult(opts) {
  const results = await chrome.scripting.executeScript(opts);
  if (chrome.runtime.lastError) {
    throw new Error(String(chrome.runtime.lastError.message));
  }
  const first = Array.isArray(results) ? results[0] : undefined;
  if (first && first.error) throw new Error(String(first.error));
  return first ? first.result : undefined;
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

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== 'rhino-reconnect') return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    backoff = 1000;
    connect();              // connect() clears any pending reconnectTimer too
  }
});

connect();
// Arm the reconnect watchdog (0.5 min period — Chrome's unpacked minimum; the
// alarm fires on schedule even if this service worker has been suspended).
chrome.alarms.create('rhino-reconnect', { periodInMinutes: 0.5 });
