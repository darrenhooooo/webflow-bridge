# Changelog

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
