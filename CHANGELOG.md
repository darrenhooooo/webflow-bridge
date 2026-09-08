# Changelog

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
