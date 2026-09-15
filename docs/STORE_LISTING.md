# Chrome Web Store submission kit — Webflow Bridge

Everything needed to fill in the Chrome Web Store item (the `dist/` zip
provides the actual package). Operator fills in the placeholder bits before
uploading.

---

## Name

**Webflow Bridge**

## Summary (≤ 132 chars)

```
Hand your browser to your AI: everything runs on your machine, and your data never leaves it.
```

(93 chars — copy as-is. Same copy for all 12 locales below.)

## Category suggestion

**Developer Tools**

---

## Full description (~120–250 words, Markdown allowed)

> **What it is.** Hand your browser to your AI: everything runs on your
> machine, and your data never leaves it. Your scripts — or any local
> automation — post commands to
> `http://127.0.0.1:10086`, and Webflow Bridge runs them in your
> real Chrome tab. It attaches to the **active tab** via `chrome.debugger` and
> executes through CDP `Runtime.evaluate` — the exact channel Chrome's DevTools
> console uses. That means arbitrary JavaScript you provide runs in the page's
> own world, immune to page Content-Security-Policy restrictions (strict sites
> like x.com included), and full CDP passthrough (`Input.*`, `Page.*`,
> `DOM.*`, `Network.*`, …) lets scripts drive every browser capability.
>
> A companion local daemon (Python stdlib only, no dependencies) ships in the
> open-source repo and is required — everything runs on your machine and
> **nothing leaves it**: no cloud, no accounts, no telemetry.
>
> **Install & use**
> 1. Load the extension at `chrome://extensions` → Developer mode → Load
>    unpacked → the `extension/` folder.
> 2. Run the daemon from the repo: `uv run --python 3.11 daemon/webflow_bridge.py`
>    (or `python daemon/webflow_bridge.py`).
> 3. Keep Chrome on a real website, then POST a command:
>
>    ```bash
>    curl -s -X POST http://127.0.0.1:10086/command \
>      -H "Content-Type: application/json" \
>      -d '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}'
>    ```
>
> **Open source.** MIT-licensed at <https://github.com/darrenhooooo/webflow-bridge>
>
> **Support / feedback.** File an issue at the GitHub repo above, or contact
> <darren.hou@outlook.com>

## Description — all 12 store locales

Manifest `description` is resolved from `_locales/<locale>/messages.json`
(`__MSG_extDescription__`, `default_locale: zh_CN`). The strings below are the
same copy, ready to paste into the Chrome Web Store summary field or the AMO
listing description — each is ≤ 132 characters. The `zh_CN` row is the
original Chinese copy; the `en` row is the English baseline.

| Locale | Extension (Chrome / Edge · CWS) | Firefox companion (AMO) |
|---|---|---|
| `zh_CN` 中文 | 把浏览器交给你的 AI：全在本机运行，数据不出本机 | Webflow Bridge Firefox 版的本机控制面板：状态、脚本、标签页管理；只连本机，不收集任何数据。 |
| `zh_TW` 繁體中文 | 把瀏覽器交給你的 AI：全在本機執行，資料不出本機 | Webflow Bridge Firefox 版的本機控制面板：狀態、指令碼、分頁管理；只連本機，不收集任何資料。 |
| `en` English | Hand your browser to your AI: everything runs on your machine, and your data never leaves it. | The local Webflow Bridge control panel for Firefox: status, scripts, tabs. Connects only to your machine, collects no data. |
| `ja` 日本語 | ブラウザをあなたの AI に任せましょう。すべてお使いのマシンで動作し、データは外部に送信されません。 | Firefox 版 Webflow Bridge のローカル操作パネル。状態・スクリプト・タブを管理。接続先はこのマシンだけで、データは収集しません。 |
| `ko` 한국어 | 브라우저를 당신의 AI에게 맡기세요. 모든 것은 이 기기에서 실행되고, 데이터는 외부로 나가지 않습니다. | Firefox용 Webflow Bridge 로컬 제어판. 상태·스크립트·탭을 관리합니다. 이 기기에만 연결하고 데이터는 수집하지 않습니다. |
| `fr` Français | Confiez votre navigateur à votre IA : tout s'exécute sur votre machine, vos données ne sortent jamais. | Panneau de contrôle Webflow Bridge pour Firefox : état, scripts, onglets. Connexion locale uniquement, aucune donnée collectée. |
| `de` Deutsch | Übergib deinen Browser deiner KI: Alles läuft auf deinem Rechner, deine Daten verlassen ihn nie. | Webflow Bridge-Kontrollpanel für Firefox: Status, Skripte, Tabs. Verbindet sich nur mit deinem Rechner, erfasst keine Daten. |
| `es` Español | Dale tu navegador a tu IA: todo se ejecuta en tu equipo y tus datos no salen de él. | Panel de control local de Webflow Bridge para Firefox: estado, scripts, pestañas. Solo se conecta a tu equipo, no recopila datos. |
| `pt` Português | Entregue seu navegador à sua IA: tudo roda na sua máquina e seus dados não saem dela. | Painel de controle local do Webflow Bridge para Firefox: status, scripts, abas. Conecta-se apenas à sua máquina, não coleta dados. |
| `ru` Русский | Отдайте браузер своему ИИ: всё работает на вашем компьютере, данные никуда не уходят. | Панель управления Webflow Bridge для Firefox: статус, скрипты, вкладки. Работает только с вашим компьютером, данные не собирает. |
| `ar` العربية | سلّم متصفحك إلى الذكاء الاصطناعي: كل شيء يعمل على جهازك، ولا تغادر بياناتك جهازك أبدًا. | لوحة التحكم المحلية لـ Webflow Bridge في Firefox: الحالة والنصوص البرمجية والتبويبات. تتصل بجهازك فقط ولا تجمع بيانات. |
| `it` Italiano | Affida il browser alla tua IA: tutto viene eseguito sul tuo computer e i tuoi dati non escono mai. | Pannello di controllo di Webflow Bridge per Firefox: stato, script, schede. Si connette solo al tuo computer, non raccoglie dati. |

## Sensitive-permission justifications (paste into the review form)

### `debugger`

The `debugger` permission is the **only** Manifest V3 channel that can
evaluate an arbitrary JavaScript *string* in a page and get the result back:

- Content-script isolated worlds run under a **Chrome-hardcoded CSP** whose
  allowed `script-src` sources omit `eval`/`new Function`, so an in-content
  evaluator cannot work in stable MV3 regardless of the manifest.
- `chrome.scripting.executeScript` no longer accepts code strings at all
  (only `files`/`func`), and compiling the string inside an injected `func`
  is blocked by **page** CSP on strict sites (verified live on x.com).

`chrome.debugger` → CDP `Runtime.evaluate` is the same channel the built-in
DevTools console uses; this extension is effectively a **local DevTools
console driven by a local daemon**. There is no remote-code-execution surface:
the companion daemon binds `127.0.0.1` only and rejects cross-origin POSTs
(Origin guard). All evaluation targets the user's own active/selected tab,
and no data leaves the device.

### `tabs`

Used to pick the tab to drive (the active tab, or a specific tab via
`tabId`), read its URL/title for listings (`tabs_list`), and navigate / open /
close / activate tabs as scripted by the local caller. Same capabilities as
the window/tab management a user performs by hand.

### `scripting`

Used **only** by an opt-in diagnostic probe (`probe` action) that compares
JavaScript-injection paths and reports the results to the local caller. The
main evaluate path never calls `chrome.scripting`.

**Data flow note for all three:** every command originates from a process on
the user's own machine (scripts or `curl` to `http://127.0.0.1:10086`). The
extension makes no network connection except the local WebSocket
`ws://127.0.0.1:10087`; no telemetry, analytics, or third-party code.

## Single purpose statement

> Let users drive their own local browser session with scripted commands from
> a local daemon.

## Privacy

- Full plain-English policy: [`PRIVACY.md`](PRIVACY.md) in the
  repo (MIT, GitHub link above).
- The Chrome Web Store upload form requires a hosted privacy-policy URL —
  publish the policy and set it to **<https://<hosted>/privacy>** (placeholder:
  operator hosts `docs/PRIVACY.md`, e.g. via GitHub Pages).

## Screenshots

Store requires at least one screenshot, **1280×800 or 640×400**. Planned
captures (operator to take later):

1. The toolbar popup (status + "Test on active tab") on a dark background.
2. A "DevTools-like" usage shot: Chrome DevTools console open on a page
   showing the equivalent `Runtime.evaluate` output, or a terminal with the
   `curl` command and its JSON reply next to the page it drove.

## Notes

- Edge Add-ons store is a separate submission from Chrome Web Store (same
  zip/listing assets; different dashboard at microsoftedge.microsoft.com/addons).
