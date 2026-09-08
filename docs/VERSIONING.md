# 版本策略（VERSIONING）— Webflow Bridge

产品版本 = **整仓单轨语义化版本**（SemVer 2.0），起点 **v0.1.1**（2026-09-08，含
Chrome/Edge 版 44/44 流程 + Firefox 版 P0 + companion 控制面板）。
0.x 阶段遵循 SemVer 0.x 约定：**minor 允许向后不兼容变更**（须在 CHANGELOG 标注
breaking），1.0.0 之前不承诺 API 冻结。

## 版本载体（一次 bump 全部同步）

| # | 载体 | 位置 |
|---|---|---|
| 1 | Chrome/Edge 扩展 | `extension/manifest.json` → `version` |
| 2 | Firefox companion 附加组件 | `ff/extension/manifest.json` → `version` |
| 3 | Chrome 版产物包名 | `tools/rebuild_zip.py` → `dist/webflow-bridge-<ver>.zip` |
| 4 | 协议文档标题 | `docs/HTTP_API.md` 首行 `Command API v<ver>` |
| 5 | git tag | `v<ver>`（同步 push 到 cnb origin） |
| 6 | 变更记录 | `CHANGELOG.md` 新增条目 |

原则：**禁止不 bump 直接改**任何协议动作行为/返回结构；行为变更必须伴随至少
patch bump 并同步上述载体。

## 什么触发版本迭代（bump 检查表）

逐项自查，命中即 bump；同时命中多项取最高档。

### PATCH（0.1.1 → 0.1.2）
- bug/安全修复：行为回到预期，协议不变
- 纯文档/文案修正（README/AMO 文案/注释），不含能力宣称变化
- 构建/打包/CI 修复（产物名同步）
- 零行为变化的重构/清理（测试全绿）
- 单后端内部实现换等价路径（如 Firefox 某动作实现改用更稳的 BiDi 命令，
  对外行为一致）

### MINOR（0.1.x → 0.2.0 / 0.3.0 …）
- **完成一个能力面** —— 天然 bump 点（与 FIREFOX_SUPPORT_PLAN 阶段对齐）：
  - P1 输入面动作全绿（click/fill/type_text/send_key/mouse_click/screenshot/
    save_as_pdf/upload）→ 0.2.0
  - P2（snapshot 生成器 / network / console / handle_dialog / file_chooser /
    humanize）→ 0.3.0
  - P3（ff-launch mac / 文档分版 / 双 daemon 回归 / Chrome 44/44 零回退）→ 0.4.0
- 协议新增动作/参数（向后兼容，客户端零改动可用）
- 新增平台后端（如 Firefox 版之后的另一浏览器）
- 新增分发渠道（如 companion AMO 上架新版本、CWS 版本更新）
- Chrome 版新自动化流程能力（44/44 基础上的新增量）

### MAJOR（0.x → 1.0.0）——以下**全部**满足才升
- Chrome + Firefox 能力对等（P1–P3 全绿）
- 协议动作集冻结（动作只修不增，或增走正式评审）
- 双平台回归通过（Chrome 44/44 + Firefox P1+ smoke 全绿）
- CWS / AMO 上架完成或正式就绪
- 文档与实测一致（README/HTTP_API/openapi 分版）

### 0.x 阶段特例
- 0.x minor 内的 breaking 变更合法，但必须：CHANGELOG 标 `[breaking]`、
  README 支持范围同步、动作集表更新。
- 尚未 tag 发布的改动不单独 bump，累积到最近一次发布点一起算；
  已 tag 版本上的缺陷修复 → 立即 patch bump（如 0.2.0 发布后发现的 bug
  → 0.2.1）。

## bump 操作流程（kf 执行，每次发布走一遍）

1. 能力完成 + 对应平台 smoke 全绿（真实环境，禁止纸面验收）
2. 同步第 1–4 号载体版本号（CRLF-safe，保留文件原行尾）
3. `CHANGELOG.md` 记变更（新增/修复/breaking 分类）
4. `git commit`（message 注明 bump 理由）
5. `git tag v<ver>` → `git push origin main` + `git push origin v<ver>`
6. 涉及产物分发时重建 zip（`tools/rebuild_zip.py`）并核对产物名

## 历史处理（2026-09-08）

- 废弃旧 1.x 编号体系（extension manifest 1.1.0、旧 tag v1.1.0）：已删除本地与
  cnb 远端 v1.1.0 tag，manifest/API 文档/zip 产物名统一回落 0.1.1。
- 0.1.1 = 「Chrome/Edge 44/44 稳定 + Firefox P0 全绿 + companion AMO 就绪 +
  安全鉴权」的完整现状快照。
