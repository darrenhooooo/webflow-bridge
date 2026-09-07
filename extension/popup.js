// Webflow Bridge popup — status surface + one-shot "test on active tab".
// Talks to background.js over chrome.runtime messages (wf-ping / wf-evaluate).
(function () {
  'use strict';

  const MAX_RESULT = 120;

  const versionEl = document.getElementById('version');
  const dotEl = document.getElementById('dot');
  const statusEl = document.getElementById('statusText');
  const testBtn = document.getElementById('testBtn');
  const resultEl = document.getElementById('result');

  let bgAlive = false;

  // Dot states: 'check' (pulsing) | 'ok' | 'bad'.
  function setStatus(state, text) {
    dotEl.className = 'dot dot-' + state;
    statusEl.textContent = text;
  }

  function showResult(ok, text) {
    resultEl.textContent = text;
    resultEl.classList.remove('hidden');
    resultEl.classList.toggle('ok', ok);
    resultEl.classList.toggle('err', !ok);
  }

  function hideResult() {
    resultEl.classList.add('hidden');
  }

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
          resolve(resp || { ok: false, error: 'no response from background' });
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

  async function ping() {
    setStatus('check', 'Daemon: checking…');
    const resp = await send('wf-ping');
    bgAlive = !!(resp && resp.ok);
    if (!bgAlive) {
      setStatus('bad', 'Extension unavailable — reload it at chrome://extensions');
      testBtn.disabled = true;
      return;
    }
    const connected = resp.daemon === 'connected';
    setStatus(connected ? 'ok' : 'bad',
              connected ? 'Daemon: connected' : 'Daemon: disconnected');
  }

  async function runTest() {
    hideResult();
    testBtn.disabled = true;
    const resp = await send('wf-evaluate', { code: '(() => document.title)()' });
    testBtn.disabled = false;

    if (!bgAlive) {
      setStatus('bad', 'Extension unavailable — reload it at chrome://extensions');
      return;
    }
    if (resp && resp.ok) {
      const title = resp.value === undefined ? '(empty title)' : resp.value;
      showResult(true, 'document.title → ' + JSON.stringify(truncate(title, MAX_RESULT)));
    } else {
      showResult(false, 'error: ' + truncate((resp && resp.error) || 'unknown error', MAX_RESULT));
    }
  }

  versionEl.textContent = 'v' + chrome.runtime.getManifest().version;
  ping();
  testBtn.addEventListener('click', runTest);
})();
