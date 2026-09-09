# Changelog

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
  （drop / fill_form / submit / wait_for / resize_page，gplp 流程专用），
  Firefox 版未实现，按需后续对齐
- 双 daemon 并存回归 09-08 全绿：Chrome smoke 6/6 + Firefox P0 4/4 +
  P1 13/13 + P2 13/13 同机并存；X/LI 44/44 全流程由 gplp 日常发布覆盖
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
