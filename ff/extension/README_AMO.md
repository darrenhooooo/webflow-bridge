# Webflow Bridge (Firefox 控制面板) — AMO 上架说明

本目录是 **Webflow Bridge for Firefox** 的 companion 扩展（控制面板）。
核心驱动不在扩展内：本地 daemon（`ff/daemon/ff_bridge.py`）通过 WebDriver BiDi
驱动 Firefox，扩展仅展示状态、执行 JS、列出标签页等控制面板功能。

## 一句话简介（AMO name / summary 用）

Webflow Bridge Firefox 版的本机控制面板：daemon/浏览器状态、执行 JS、列出标签页。

## 描述（description，≤132 字符）

Webflow Bridge Firefox 版的本机控制面板：显示 daemon/浏览器状态、执行 JS、列出标签页。仅连接本机 127.0.0.1:10096，不收集任何数据。

## 权限与理由（最小权限）

| 声明 | 用途 | 为何必要 |
|---|---|---|
| `storage` | 缓存 daemon token 与最近 5 条执行历史 | 均在本地 profile，不上传 |
| `http://127.0.0.1/*` | fetch 本机 daemon（HTTP POST /command + GET /config） | 控制面板的唯一数据源；MV2 下 host 模式按规范放在 `permissions`（AMO linter：`host_permissions` 仅 MV3 支持），不含 `<all_urls>` |

未使用的权限/能力：无 background 页、无 content script、无 `<all_urls>`、
无 nativeMessaging、无 debugger/标签页读取 API、不连 BiDi WebSocket。

## 隐私说明

- 不收集、不上传、不存储任何用户数据或页面内容；扩展页面只访问
  `http://127.0.0.1:10096`（本机 daemon）。
- 用户主动输入的 JS 只发往本机 daemon，由 daemon 在用户自己打开的 Firefox
  页面内执行（本地自动化用途）。
- 扩展无远程代码、无统计埋点；源码即本目录，可审查（MIT）。

## 版本/兼容

- `manifest_version: 2`（Firefox MV2，AMO 仍接收；稳定、无 MV3 字符串执行收紧风险）。
- `browser_specific_settings.gecko.id`：开发期固定 `webflow-bridge-ff@webflow.local`；
  **上架前改为正式 ID** 并升版。
- `strict_min_version: 140`（与 README「推荐 140+」一致）；AMO linter 提示
  `data_collection_permissions` 键在 Firefox for Android 需 142+ —— 本 companion
  仅面向桌面 Firefox（驱动本机 daemon），不发布 Android 变体，故保留 140。
- `data_collection_permissions: {required: ["none"]}`：AMO 新政策要求，声明零数据收集。
- 建议 Firefox 129+（实测 155.0.1）。

## 上架前 checklist

- [ ] 正式 gecko id（非 `.local`）与 version
- [ ] 图标：icon{16,32,48,96}.png 已由 make_icons.py 生成
- [ ] 源码包（本目录）随提交，满足 AMO 源码可审要求
- [ ] AMO 自检清单：无远程内容、无混淆、无 <all_urls>
