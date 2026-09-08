# Webflow Bridge for Firefox — 独立版产品方案（2026-09-08 定稿；实施状态见 §4，09-08 P0/P1/P2 已完成并发布 v0.1.1/v0.2.0/v0.3.0）

## 0. 产品定位

**独立产品：Webflow Bridge for Firefox**（不是 daemon 加后端，是 Chrome 版的 Firefox 变体）。
- 目标：能力对等的 Firefox 版——同一套 HTTP `/command` 协议与动作契约，脚本只需换端口即可从 Chrome 版迁移。
- 用户视角：驱动「用户日常在用的 Firefox」（真实 profile、登录态、cookie 全保留），像 Chrome 版驱动日常 Chrome 一样。
- 分发：核心 = Firefox BiDi 直连 daemon + 启动器；**AMO 上架 companion 附加组件做配角**（品牌/状态/引导，非能力载体）。
- 不触碰：Chrome/Edge 版代码与 44/44 流程零改动；两版可同机并存（不同端口）。

## 1. 平台事实（2026-09-08 Firefox 155.0.1 本机实测）

| # | 事实 | 影响 |
|---|---|---|
| 1 | 普通启动的 Firefox 无任何调试监听口，事后 attach **不可能** | Firefox 必须从启动时带 `--remote-debugging-port`（平台约束，无法绕过） |
| 2 | 真实 profile + 该参数启动 → BiDi 正常，登录态保留 | 「日常 Firefox」= 启动器开的真实 profile 实例 |
| 3 | BiDi 会话 `navigator.webdriver=true`，user.js 注入关不掉 | Firefox 版有自动化指纹；不承诺反爬对抗 |
| 4 | BiDi evaluate 在 x.com（严格 CSP）成功 | CSP-immune 成立，与 Chrome 版同水准 |
| 5 | session.new / navigate / getTree / captureScreenshot 全通 | BiDi 基础链路可用 |
| 6 | 无 chrome.debugger API（MDN 确认）；CDP 已从 Firefox 移除 | 唯一通道 = WebDriver BiDi |
| 7 | AMO 政策：必须提交可审查源码（MIT 开源即满足） | 上架无障碍 |
| 8 | Firefox MV3 持续收紧字符串执行（149-152 移除注入类能力） | companion 附加组件不做能力载体，规避该风险 |

## 2. 架构

```
Chrome 版（现状，不动）                    Firefox 版（新增，独立）
script → POST :10086 → daemon → WS → MV3 扩展 → debugger → Chrome tab
script → POST :10096 → ff_daemon → BiDi ws://127.0.0.1:9222/session → Firefox
                                ↑
                     ff-launch（真实 profile + --remote-debugging-port 9222）
                                ↑
                     AMO companion 附加组件（状态/启动/引导，可选安装）
```

### 2.1 组件清单（独立 Firefox 版目录）

| 组件 | 说明 |
|---|---|
| `ff/daemon/ff_bridge.py` | 独立 daemon：HTTP `POST :10096/command`（协议同 Chrome 版）+ BiDi 客户端直连 Firefox。Python stdlib only（RFC6455 已有实现可复用 Chrome 版 daemon 的 framing 代码） |
| `ff/ff-launch.bat` / `.command` / `.lnk` | 启动器：解析 profiles.ini 找 Default profile → `firefox.exe -profile <真实profile> --remote-debugging-port 9222`。幂等：若该 profile 已在跑则提示先关闭。不新建/复制 profile |
| `ff/extension/`（companion，AMO 上架） | 薄附加组件：工具栏显示 daemon 连接状态 / 一键启动 ff-launch / 显示 token / 跳转文档。无 debugger、无 <all_urls>、无内容注入 → AMO 低风险 |
| `ff/docs/` | 安装/使用/FAQ（中英）；明确 Firefox 指纹特性与支持范围 |
| 复用 | Chrome 版协议文档/动作契约/鉴权模型（token 文件、/config、Bearer）原样照搬，端口换 10096 |

### 2.2 端口与并存

- Firefox 版 daemon：HTTP `127.0.0.1:10096`；BiDi 固定 `9222`（可 `--ff-port` 覆盖）。
- 与 Chrome 版（10086/10087）无冲突，双 daemon 可同时跑。
- 鉴权：同款共享 token（`~/.webflow_bridge_ff/token`），HTTP Bearer + BiDi 会话前校验（见 §4 安全）。

### 2.3 动作契约（与 Chrome 版对齐）

| 动作 | Firefox 实现 | 状态 |
|---|---|---|
| evaluate | script.evaluate（realm→context） | P0 |
| navigate / tabs_open / tabs_close / tabs_activate / tabs_list / find_tab | browsingContext.* + getTree | P0 |
| click / fill / type_text / send_key / mouse_click | script 定位 + input.performActions（真实输入） | P1 |
| screenshot / save_as_pdf | browsingContext.captureScreenshot / print | P1 |
| upload | input.setFiles（待验证） | P1* |
| probe | 自定义健康矩阵（连接/session/context） | P0 |
| snapshot | DOM→a11y 快照生成器（script 实现） | P2 |
| list_network_requests / list_console_messages | network.* / log.* 事件订阅 | P2 |
| handle_dialog / handle_file_chooser | BiDi 事件（待验证） | P2* |
| humanize | input 序列随机节奏（后端实现） | P2 |
| cdp | **不支持** → 明确错误 `{"error":"cdp not supported on firefox backend"}` | P0 |

## 3. 安全模型

- **本地鉴权**：ff daemon 独立 token（同 Chrome 版机制），HTTP Bearer 校验；`/config` 供 companion 附加组件引导。
- **BiDi 通道防护（关键待验证）**：Firefox remote agent 在 `ws://127.0.0.1:9222/session` 是否校验 Origin？若恶意网页可 `new WebSocket('ws://127.0.0.1:9222/session')` 抢会话/发命令，必须加防护：
  - 首选验证：Firefox 是否拒绝带非 localhost Origin 的 WS 握手（Chrome 的 remote debugging 有此防护）。
  - 若无防护：ff-launch 增加前置检查（确认 9222 仅 127.0.0.1 监听）+ README 安全说明；必要时引导 Firefox 用 `remote.force-local` 类设置（Firefox remote agent 有 local-only 默认，需实测确认）。
- **指纹如实告知**：`navigator.webdriver=true` 无法关闭，README 明示；产品定位「自动化自己已登录站点」，不承诺反爬。

## 4. 分阶段实施（pi 执行口径）

| 阶段 | 内容 | 验证标准 | 状态 |
|---|---|---|
| P0 | ff daemon 骨架：HTTP :10096 + token 鉴权 + BiDi 连接（session.new/getTree/navigate/evaluate/tabs_list/tabs_open/close/probe）+ cdp 明确报错 + ff-launch(win) | 启动器开真实 profile Firefox，`evaluate document.title` 返回真实页面；Chrome 版 daemon 不受影响可并存 | ✅ v0.1.1 (09-08) |
| P1 | 输入面：click/fill/type_text/send_key/mouse_click/screenshot/save_as_pdf/find_tab/tabs_activate + upload(若 setFiles 可行) | 对照 Chrome p0_smoke 用例集在 Firefox 跑通核心闭环 | ✅ v0.2.0 (09-08) |
| P2 | snapshot DOM→a11y 生成器 + network/console 事件 + handle_dialog/file_chooser + humanize | snapshot/click 循环可用；事件类动作有输出 | ✅ v0.3.0 (09-08)；file_chooser 实测 Firefox BiDi 无拦截机制→明确报错引导 upload |
| P3 | companion 附加组件（AMO 就绪：manifest/图标/隐私/源码可审）+ ff-launch(mac) + 文档（README 双语/HTTP_API/openapi 分版）+ 双 daemon 回归 | AMO 自检清单齐；文档与实测一致；Chrome 44/44 零回退 | 🔄 companion 已提前完成 (v0.1.1)；mac 启动器 + 文档分版 09-08 进行中 |
| P4 | （可选）AMO 提交 + 上架运维 | 上架通过 |

预估：P0 1天；P1 1-2天；P2 2-3天；P3 1天。合计 5-7 人日。

## 5. 待验证项（编码前/中补测）

1. Firefox remote agent WS 握手是否校验 Origin（§3 安全关键，P0 首查）
2. input.setFiles 在 Firefox 的实际行为（upload 动作可用性）
3. handle_dialog（alert/confirm）在 BiDi 事件模型的实现路径
4. BiDi RemoteValue ↔ 现有 `data.value` 返回值契约的序列化适配
5. Firefox 重启后 daemon 的 reconnect/会话恢复
6. profiles.ini 多 Default profile 的选择规则
7. macOS ff-launch 与双机部署对齐

## 6. 取舍与风险

- 取舍：cdp 透传、snapshot 在 Firefox 版是降级或重实现；能力面以 §2.3 为准，README 如实标注。
- 风险：WebDriver BiDi 仍在演进（Firefox 里程碑推进），个别动作随版本变化；锁定版本下限（实测 155，README 建议 129+/推荐 140+）。
- 合规：AMO companion 薄附加组件低风险；核心 daemon 不开源上架（本地工具），companion 源码可审。
- 回退：Chrome/Edge 版零改动；Firefox 版独立目录独立端口，删除即干净。

## 7. 验收清单（darren 审）

- [x] ff-launch 用真实日常 profile 打开 Firefox，登录态可见（09-08 多次 smoke 实证
      default-release 真实 profile，规则1 Install 段命中）
- [x] ff daemon 能驱动该 Firefox 完成 evaluate/navigate/click/fill 基础闭环
      （P0/P1/P2 smoke 全绿：ff_smoke 4/4 + ff_p1_smoke 13/13 + ff_p2_smoke 13/13）
- [x] Chrome 版零回退（双 daemon 并存回归 09-08：Chrome smoke 6/6 + Firefox 全套
      同机并存全绿；X/LI 44/44 全流程属 gplp 日常发布覆盖）
- [x] companion 附加组件 AMO 就绪（manifest/图标/隐私/源码可审，README_AMO.md）
      （加载到 Firefox 的 UI 实测待 P4 上架前进行）
- [x] README 明确 Firefox 支持范围、指纹限制、安装三步（ff/README.md 完整版
      09-08：全动作矩阵 + 双平台 + 已知边界）
