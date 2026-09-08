# Webflow Bridge — 防滥用 / 反检测 / 上架合规 方案（2026-09-08）

范围：darren 指定三方向并集。
结论先行：P0 补本地鉴权（当前本机任意进程/恶意网页可无鉴权驱动浏览器，实锤）；
stealth 能力已过半（chrome.debugger 通道本身无 WebDriver 指纹），补行为层即可；
上架材料与 stealth 互相打架——产品叙述永远不写"绕过反爬"，stealth 只进代码不进文案。

---

## 一、威胁模型与现状（先摆事实）

### A. 防滥用/劫持（方向 2）—— 当前最危险
现状（daemon/webflow_bridge.py 代码级实锤）：
| 面 | 现状 | 风险 |
|---|---|---|
| HTTP POST /command | 无任何鉴权；Origin 白名单仅挡浏览器带 Origin 的请求；无 Origin（curl/脚本）永远放行 | 本机任意进程 = 完整浏览器控制权（读 cookie/会话、操作已登录账号、访问内网） |
| Origin 白名单含 "null" | 注释自述为 sandbox/file 页面兜底 | 恶意网页开 sandboxed iframe → fetch Origin:null → 命中白名单 → 命令照发（fire-and-forget，无需读响应）。典型 localhost CSRF |
| WS :10087 握手 | 完全不受 Origin guard 保护，无共享密钥 | 本机恶意进程可自行连 WS，且单槽先到先得可抢扩展的连接 |
| CDP dispatch | 注释自述 "no method allowlist" | evaluate/cdp 全能力透传，无最小权限 |

### B. 被目标站反爬识别（方向 1）—— 技术底子已好于 Selenium 系
有利事实：
- Webflow 走 chrome.debugger（DevTools 同款 CDP），非 WebDriver → 无 `navigator.webdriver`、无 `--enable-automation`、无 headless 标志；真实浏览器真实登录态，TLS/UA 指纹与真人无差别。这层已天然绕过多数指纹检测。
- 已实现 mouse_click（Input.dispatchMouseEvent 真实输入事件）、type_text/insertText——本就是 stealth 友好路径。
可补缺口（行为层）：
- 纯 el.click()/fill 合成事件 vs 真实输入事件的占比；无人工节奏（恒定间隔、零延迟）易被行为分析揪出。
- 无滚动/鼠标轨迹模拟；Selenium 常见检测点（如 `window.cdc_`）不适用，但 CDP 附加本身极难被页内 JS 察觉——优势要保住，别引入 content script。

### C. 上架/合规（方向 3）—— 与 A/B 的张力
现状：README/STORE_LISTING 已无 kimi、叙述为"本地自动化桥/开发者工具"，Typical uses 含 "Scraping & monitoring"。
张力：
- 商店与 ToS 红线 = "规避访问控制/反爬、解锁、验证码绕过"。stealth 功能若写进 README/商店文案 = 主动递刀。
- "Scraping" 字样本身在 Developer Tools 类目风险中等，可留；"stealth/anti-detect/bypass" 字样零容忍。

---

## 二、措施分级（按优先级）

### P0 — 本地鉴权（方向 2，先做，工作量小）
1. **共享密钥**：daemon 启动生成随机 token（~/.webflow_bridge/token，0600 权限）：
   - HTTP：所有 POST 必须带 `Authorization: Bearer <token>`，否则 401。Origin guard 保留为第二道。
   - WS 握手：扩展连接时在 Sec-WebSocket-Protocol 或 query 里带 token，daemon 校验后才接受。
   - 向后兼容开关：`--allow-no-auth` 仅本机个人脚本迁移期用，README 标注不推荐。
2. **移除 "null" 出白名单**（或收紧：带 Origin:null 且无 token 一律拒）——堵 sandbox iframe 通道。
3. **请求审计日志**：默认 info 记录 action+来源 IP+时间；可选 `--audit <file>` 全量 JSONL。
4. dispatch 层加 CDP 方法最小白名单开关（默认关，`--cdp-allowlist` 可开，注明会破坏全能力透传）。

取舍：token 让"零配置 curl 直发"变多一步——用 `daemon/webtool` 小脚本或环境变量 WBF_TOKEN 自动带，保持脚本零改动心智。

### P1 — 行为层自然化（方向 1，代码内做、文案不提）
1. 新增可选"humanize"参数（action 级 args.humanize=true 或 daemon 全局 --humanize）：
   - 输入前随机 200–900ms 延迟、事件间随机抖动；
   - 默认合成事件 → Input.dispatch* 真实事件优先（已有点，补 fill 的 value 模式切换）；
   - 可配每步后随机 scroll 微动。
2. 不做：验证码自动求解、验证码绕过、指纹伪造（三者均越过红线，且商店/ToS 高危）。
3. 保持 chrome.debugger 通道纯净：不引入 content script、不注入 `window.cdc_` 类痕迹。

### P1 — 上架合规（方向 3）
1. STORE_LISTING/README 全量扫词：禁 "bypass/anti-detect/stealth/unlock/evade"；改述为"自动化真实浏览器操作"。
2. "Scraping & monitoring" 保留但加限定语："for content you already have access to / your own data"（避免"爬别人站"暗示）。
3. 仓库 README 加 Usage 边界段：仅限本人账号/已授权站点、遵守目标站 ToS；不提供验证码绕过。
4. 商店用途分类维持 Developer Tools；权限正当性文案 STORE_LISTING 已备，勿加"unrestricted CDP"类夸大。

---

## 三、红线（三方向交集的最终约束）
- stealth 只作为代码行为参数存在，永不写入公开文案/商店描述。
- 验证码绕过、访问控制规避、指纹伪装：一律不做、不提、不演示。
- 鉴权是本地工具，不是反爬对抗——别把 P0 与方向 1 混为一谈。

---

## 待实验验证项（不猜，落地前补测）
- sandboxed iframe → POST Origin:null → daemon 实际放行（代码已明示放行，补一次端到端确认）。
- 恶意进程无 token 驱动浏览器的完整利用链演示（用于说服加鉴权必要性）。
- WS 无鉴权连接实际能否被第三方抢槽（单槽语义验证）。
