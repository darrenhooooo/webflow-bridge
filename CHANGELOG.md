# Changelog

## v1.3.0 — 2026-09-16

Minor bump: language coverage grows from 12 to 16 and the product description
now uses the browser's own localization mechanism. The protocol action set is
unchanged (no new action, no new parameter).

### Added
- **Four new UI languages: Vietnamese, Thai, Indonesian and Hindi.** The popup
  is now localized in 16 languages (en, ja, ko, fr, de, es, pt, ru, ar, it, vi,
  th, id, hi, zh-CN, zh-TW) — 30 keys per language in the Chrome/Edge popup and
  83 in the Firefox companion. The activation / inactive guidance (the three
  state words, the four checklist rows, both failure reasons, reconnect and
  disconnect, copy and copy-failed, re-check) is written per language rather
  than translated word for word; the two entries whose meaning differs between
  the editions (`reason_daemon_busy`, `row_page`) are translated separately.
- Language matching accepts `vi` / `th` / `id` / `hi`, and the legacy
  Indonesian code `in` now falls back to `id`.

### Changed
- **The product description now follows the browser's own localization.** Both
  manifests use `__MSG_extDescription__` with `default_locale: zh_CN` and ship
  16 `_locales/<locale>/messages.json` each, so a store listing shows the
  visitor's own language. The text reads differently per edition by design: the
  Chrome/Edge extension says "hand your browser to your AI — everything runs on
  your machine, your data never leaves it", while the Firefox companion
  describes itself as the local control panel (status, scripts, tabs) that only
  connects locally.
- Every carrier of the old wording was updated with it: README (EN + zh-CN),
  docs/STORE_LISTING.md (16-language table), the first line of docs/PRIVACY.md,
  the openapi description, and the daemon module docstring (string only, no
  logic change).

## v1.2.5 — 2026-09-16

Batched release — the first release point since **v1.2.0**. The v1.2.1 / v1.2.2
sections below were never tagged or released, so everything in them ships here
too. The protocol action set is unchanged (no new action, no new parameter),
hence a patch bump rather than a minor.

### Added
- **The popup's main card now tries to connect when clicked in the inactive
  state**, instead of only printing an activation checklist. Clicking sends the
  new `wf-dial-now` background message — it clears the pending backoff timer,
  resets the backoff and dials the daemon WebSocket once — and the popup then
  polls `wf-ping` every 150 ms for ~3 s, without blocking the regular 2 s status
  poll. A daemon that is up therefore goes from `inactive` to `active` in tens
  of milliseconds. Only if dialling fails is the checklist shown, and its
  **first line now names the determined reason**: daemon not running, or daemon
  running but the slot held by another browser. A paused state sends
  `wf-reconnect` first; the deliberate "user disconnected" state is
  intentionally unchanged (the card still does nothing there — the reconnect
  button owns it). The Firefox edition is isomorphic, with its own wording for
  `reason_daemon_busy`; the Chrome/Edge wording is untouched.

### Fixed
- **Native JavaScript dialogs no longer freeze the bridge.** `alert` /
  `confirm` / `prompt` / `beforeunload` are auto-accepted as soon as they open
  (runtime policy switch: `set_dialog_policy` / `--no-auto-dialog`), and every
  `chrome.debugger.sendCommand` now carries a 30 s cap that resets the dead
  session and fails with a self-explaining error instead of waiting out the
  daemon's 120 s round-trip limit. Full detail in the v1.2.1 section below.
- **Dialog blocking is scoped per tab, and `handle_dialog` is race-proof.** A
  dialog on one tab no longer leaks onto another, manual mode fails in
  milliseconds instead of 30 s, and a `not attached` / `detached` transport
  error is retried exactly once after a re-attach. Full detail in the v1.2.2
  section below.

### Documentation
- `docs/VERSIONING.md`: the three-part version rule is now written out
  explicitly — the patch position takes only **0** (the minor/major release
  point), **1** (an urgent single fix, which ships immediately and is exempt
  from batching) or **5** (a batched release after 5 patch-level commits).
  Intermediate values are no longer used. v1.2.1 / v1.2.2 predate the rule and
  stay as they are; how a second batching round inside the same minor is
  numbered is left as `TODO(darren)` rather than invented.

### Build
- The GitHub mirror workflow now mirrors CNB tags and publishes a GitHub
  Release per new tag, building each package from that tag's own tree (the
  rebuild scripts hardcode the version, so building on `main` would ship the
  wrong sources for old tags) and using the matching CHANGELOG section as the
  release notes. Per-tag failures are counted and reported as a non-zero exit
  instead of aborting the loop. Backfilling old tags downgrades the GitHub App
  workflow restriction to a warning naming the manual command, while still
  failing the job on any other error, and releases are only created for tags
  that really exist on origin.
- All version carriers synced to 1.2.5: both manifests, `docs/HTTP_API.md`,
  `openapi/openapi.yaml`, both `rebuild_zip.py` package names, `README.md`,
  `README.zh-CN.md` and `SECURITY.md`.

## v1.2.2 — 2026-09-16

### Fixed
- **Manual dialog mode no longer makes the caller wait 30 s.** While a native
  dialog is pending (`dialog_policy: manual`, or an auto-accept that failed),
  a debugger action on that tab now fails in milliseconds with the dialog's
  type/message/source URL and the two ways out. The command no longer detaches
  the session, so `handle_dialog` still owns it and resolves the dialog.
  Known boundary (unchanged): a dialog that was already open BEFORE the
  debugger attached fires no `Page.javascriptDialogOpening`, so it still falls
  back to the 30 s timeout and cannot be resolved programmatically.
- `handle_dialog` is race-proof against a dead/being-detached session: a
  `not attached` / `detached` transport error is retried exactly once after a
  re-attach, and the timeout path no longer detaches a session that owns a
  pending dialog.
- `probe` answers in milliseconds while a dialog blocks the tab (previously it
  hung): `dialog.blocking` is `true` and every injection path is marked
  `skipped: ...`.
- **Dialog state is now tab-scoped.** A native dialog on one tab no longer
  leaks onto another: `dialog.pending` carries its owning `tabId`, the
  `evaluate`/`click`/`screenshot` fast-fail and the `probe`
  `blocking`/`skipped` marking are evaluated per tab, and a `probe` on tab B
  runs its full path matrix (and `evaluate` works normally) while tab A is
  blocked. The dialog tab's debugger session is kept attached across a switch
  to another tab, so switching back still finds the dialog and `handle_dialog`
  resolves it (a re-attach used to make it unresolvable).
- Attach-time domain setup is now best-effort in parallel and no longer resets
  the freshly attached session on timeout.

### Documentation
- `docs/HTTP_API.md` / `openapi/openapi.yaml`: manual-mode fast-fail error
  shape, `probe` dialog behaviour and `dialog.blocking`, and the headless
  `screenshot {fullPage:true}` `Page is too large.` limitation.

## v1.2.1 — 2026-09-15

### Fixed
- Native JavaScript dialogs (`alert` / `confirm` / `prompt` / `beforeunload`) no
  longer freeze the bridge. They are now **accepted automatically** as soon as
  they open, so a blocked page unblocks by itself and the next command succeeds
  in milliseconds. If an automatic accept fails, the failure is surfaced
  (`GET /status` → `last_notice`, `probe` → `dialog.lastError`, and a `notice`
  on the next `/command` response) instead of being swallowed.
- Every `chrome.debugger.sendCommand` now has a timeout. A command stuck behind
  a dialog or a dead debugger session fails in ~30 s with a self-explaining
  error instead of silently waiting out the daemon's 120 s round-trip cap. The
  timed-out session is reset so the next command re-attaches.
- Downloads are no longer invisible: `navigate` to a `Content-Disposition:
  attachment` URL reports `download_started` (name + URL) and the record is
  queryable via the new `list_downloads` action. The download destination is
  unchanged.
- A page that opens a popup (`target="_blank"` / `window.open`) now produces a
  `control_moved` notice carrying the new tab id and URL; `tabs_list` is
  unchanged.
- Browser error pages are classified instead of opaque: protected pages
  (`chrome://` / Web Store), failed-to-load / certificate / cancelled-auth
  pages (`chrome-error://chromewebdata/`), and `Cannot attach to this target.`
  now read differently.

### Added
- `handle_dialog` is now documented (args, reply shape, the 2000 ms wait, and
  the error when no dialog is showing).
- `set_dialog_policy` (`auto-accept` | `manual`) switches native-dialog
  handling at runtime, with no browser action required. The daemon's
  `--no-auto-dialog` CLI flag selects `manual` at startup; `GET /status`
  exposes the live policy as `dialog_policy`. Both Chrome/Edge and Firefox
  editions default to `auto-accept`.
- `GET /status` now also reports `extension_stale`,
  `last_extension_frame_ms_ago`, `dialog_policy` and `last_notice`, and its
  documentation makes clear it is connection-only (use `probe` for an activity
  check).
- `tools/blocking_range.py`: a self-contained stdlib range reproducing the
  beforeunload / alert / confirm / prompt / download / slow / plain / popup /
  form / big-page scenarios for regression testing.

### Changed
- Daemon round-trip timeout messages now carry diagnostics (dialog / debugger
  session / extension worker) instead of only "extension did not reply".
- Firefox: `browsingContext.userPromptOpened` is auto-accepted through
  `browsingContext.handleUserPrompt`. Measured on Firefox 155: `alert` /
  `confirm` / `prompt` accept cleanly; a `beforeunload` prompt does emit
  `userPromptOpened` (with `type: "beforeunload"`) but is not answerable — the
  accept is refused with `no such alert` and the navigation proceeds; the
  failure is recorded in `probe` → `dialog.lastError`.

Backward-compatible additions and fixes (PATCH bump, see
`docs/VERSIONING.md`): existing response fields/shapes, endpoints and
auth/origin behaviour are unchanged.

Both Chrome/Edge (`extension/`) and Firefox companion (`ff/`) manifests bumped
in sync.

## v1.2.0 — 2026-09-15

### Added
- Daemon: every `POST /command` response now carries a top-level `browser` field
  (`"chrome"` / `"edge"` / `""` when no extension is connected), so a client can
  tell which browser the extension is running in without guessing.
- New `GET /status` endpoint (bearer-token authenticated) reports connection
  state without triggering any browser action: `extension_connected`, `browser`,
  `ws_port`, `connected_since`.

### Fixed
- A reconnecting extension no longer deadlocks the bridge: a new WebSocket
  connection now takes over the slot immediately and the stale connection is
  kicked, along with any command already handed to it (previously the daemon
  stopped accepting new connections and had to be restarted).
- An extension socket that is dead but still TCP-open is now detected and
  dropped: liveness is judged by the extension's application-level heartbeat
  (its `{"type":"ping"}` frames), so in-flight commands fail fast (503)
  instead of waiting out the 120 s round-trip timeout.

Backward-compatible additions (MINOR bump, see docs/VERSIONING.md): existing
response fields/shapes, endpoints and auth/origin behaviour are unchanged.

Both Chrome/Edge (extension/) and Firefox companion (ff/) manifests bumped in
sync.

## v1.1.0 — 2026-09-10

### Added
- Popup rebuilt as a whole-card status display with an activation checklist wizard
- 12-language i18n (en/zh-CN/zh-TW/ja/ko/fr/de/es/pt/ru/ar/it)
- Copy buttons embedded in command code boxes (icon-only, GitHub style)
- Restricted-page hints now browser-specific (chrome:// vs edge://)

### Changed
- Activation checklist row order (Extension ready first)
- Title removed
- Raw browser error no longer echoed for restricted pages (native "Cannot access chrome:// and edge:// URLs" suppressed)

Both Chrome/Edge (extension/) and Firefox companion (ff/) updated in sync.

## v1.0.0 — 2026-09-09

**收口发布**：Chrome/Edge 版 + Firefox 版能力对等完成，公开协议动作集冻结
（MAJOR bump，见 docs/VERSIONING.md）。

### 收口内容
- Firefox 版补齐 tabs_close_all_but（对齐 Chrome 语义：默认 active/首个
  context、显式目标失效明确报错不静默全关）
- 能力对等终核：Firefox 覆盖公开协议动作集 100%（24 动作，含 2 项平台物理
  不支持项 cdp / handle_file_chooser 明确报错并引导替代）
- 已知差异（不阻塞）：Chrome 版另有 5 个未文档化扩展面动作
  （drop / fill_form / submit / wait_for / resize_page，特定流程专用），
  Firefox 版未实现，按需后续对齐
- 双 daemon 并存回归 09-08 全绿：Chrome smoke 6/6 + Firefox P0 4/4 +
  P1 13/13 + P2 13/13 同机并存；X/LI 44/44 全流程由日常发布覆盖
- 上架就绪：CWS STORE_LISTING / AMO README_AMO + dist zip 产物
  webflow-bridge-1.0.0.zip（rebuild_zip.py）

## v0.4.0 — 2026-09-08

Firefox 版 P3 完成（MINOR bump，见 docs/VERSIONING.md）。

### 新增
- ff/ff-launch.sh：macOS 版启动器（真实 profile 规则 1/2/3、幂等、binary 三级
  定位、lsof/nc 探测；bash -n PASS + 逻辑 harness 10/10；**待 mac 实测**清单 8 项
  见脚本头注释）。.gitattributes 强制 *.sh eol=lf。
- 文档分版：ff/README.md 完整版（全动作矩阵 P0/P1/P2 + 2 项明确不支持、双平台
  安装、已知语义/边界）；README.md / README.zh-CN.md 支持范围更新（Firefox
  独立版）；docs/CROSS_PLATFORM.md 加 Firefox edition 矩阵；docs/FIREFOX_
  SUPPORT_PLAN.md 阶段状态标注。

## v0.3.0 — 2026-09-08

Firefox 版 P2 能力面完成（MINOR bump，见 docs/VERSIONING.md）。

### 新增（Firefox 版 ff/daemon/ff_bridge.py）
- snapshot：页面注入 a11y 快照生成器（ff/daemon/ff_snapshot_gen.js），返回
  {url,title,nodes[ref @eN 连续/tag/role/name/text/path]}；ref→path 缓存，
  click/fill 支持 @eN（DOM 变更后 stale 需重新 snapshot）
- list_network_requests / get_network_request：BiDi network 事件订阅 →
  daemon 侧环形缓冲（cap 300，会话内累积，契约对齐 Chrome）
- list_console_messages：log.entryAdded 订阅，type/text/timestamp，
  exception 归 type=exception，截断同 Chrome（2000/500）
- handle_dialog：browsingContext.userPromptOpened/Closed 单槽状态机 +
  handleUserPrompt；accept/action 双写、promptText、无 dialog 明确报错
- humanize：--humanize / body 顶层 / args.humanize 三源；input 动作
  pre-delay 200-900ms + 逐键 30-120ms
- handle_file_chooser：Firefox BiDi 无原生拦截机制 → 明确报错并引导用
  upload（input.setFiles），不假装支持

### 测试
- ff/daemon/test_page_p2.html + ff_p2_smoke.py 13/13 PASS（跑两遍验证幂等）；
  P0 ff_smoke 4/4 + P1 ff_p1_smoke 13/13 回归全绿
- 已知语义：click 触发 dialog 时 performActions 挂起直至 handle_dialog
  并发处理（客户端须并发发 handle_dialog）

## v0.2.0 — 2026-09-08

Firefox 版 P1 能力面完成（MINOR bump，见 docs/VERSIONING.md）。

### 新增（Firefox 版 ff/daemon/ff_bridge.py）
- click：CSS selector 真实 pointer 点击（元素中心/坐标），返回 success/tag/text
- fill：input/textarea/select 走 native setter + input/change（React-safe）；
  contenteditable 走真实点击 + 逐字键入；mode=auto/value/contenteditable
- type_text：真实 key 事件逐字输入（含中文、\n、emoji）
- send_key：协议键码映射 keyDown/keyUp（含修饰键组合）
- mouse_click：selector 元素中心或 x/y 视口坐标
- screenshot：PNG/JPEG（quality、element clip、fullPage=origin document），
  返回真实像素尺寸（自图片头解析）
- save_as_pdf：browsingContext.print → PDF base64
- upload：input.setFiles（BiDi，实测可用，change 事件触发）
- 默认 tab 语义对齐 Chrome：无 tabId/context 时优先可见（active）top-level
  context

### 测试
- ff/daemon/test_page.html（本地测试页）+ ff/daemon/ff_p1_smoke.py 13/13 PASS
  （本地 http.server，无外网依赖）；P0 ff_smoke 4/4 回归全绿

## v0.1.1 — 2026-09-08

起点版本（废弃旧 1.x 编号体系，统一回落 0.x）。

### 包含能力
- Chrome/Edge 版：Webflow Bridge daemon(:10086/WS:10087) + MV3 扩展 + 全动作集
  （evaluate/cdp/snapshot/click/fill/upload/screenshot/save_as_pdf/mouse_click/
  send_key/type_text/tabs_*/find_tab/probe/navigate 等），X/LinkedIn 发布流程
  44/44 全自动验证
- 安全：P0 shared-secret 鉴权（HTTP Bearer + WS ?token + /config bootstrap +
  audit + CDP allowlist）
- Firefox 版（独立）：ff daemon(:10096) BiDi 直连 + ff-launch(真实 profile,
  Windows) + P0 动作集 + smoke 4/4 全绿（evaluate/navigate/tabs_list）
- Firefox companion 附加组件：控制面板（状态/执行 JS/tabs/token），AMO 就绪
- 全仓术语统一（Chrome 语境用「扩展」，Firefox 语境用「附加组件」）

### 变更
- 版本体系从 0.1.1 起算，见 docs/VERSIONING.md
