# Install & operations — Webflow Bridge

**English** · [中文](#中文)

Everything here is detail that would otherwise bloat the README. If you only
want the shortest path, the README install section is enough.

---

## English

### Requirements

- **Python 3.11+** for the daemon. Everything is stdlib — no `pip install`.
- **Chrome, Edge or Firefox.** Chrome/Edge use the unpacked `extension/`;
  Firefox uses its own edition under `ff/`.
- **Windows:** use a real Python 3.11+ interpreter. The Microsoft Store
  "python.exe" is an app-execution stub that silently misbehaves — install
  from [python.org](https://www.python.org/) or use `uv`. The example commands
  use `py -3.11` on purpose.
- **Optional:** [uv](https://astral.sh/uv/) lets you skip a system Python:
  `uv run --python 3.11 daemon/webflow_bridge.py`.

### Chrome / Edge (macOS · Linux · Windows)

**1. Start the daemon** from the repo root. Pick either way:

```bash
# direct Python
python3 daemon/webflow_bridge.py          # macOS / Linux (Git Bash on Windows works too)
py -3.11 daemon/webflow_bridge.py         # Windows

# or, with uv installed (any OS)
uv run --python 3.11 daemon/webflow_bridge.py
```

You should see the banner with both listening ports:

```
========================================
  Webflow Bridge daemon started
    HTTP  : http://127.0.0.1:10086    POST /command
    WS    : ws://127.0.0.1:10087          Chrome / Edge extension connects here
========================================
```

**2. Load the extension** — once, ~30 seconds, manual by design (nothing is
ever auto-installed):

1. Open `chrome://extensions` (Chrome) or `edge://extensions` (Edge).
2. Turn on **Developer mode** (top-right toggle, identical in both browsers).
3. **Load unpacked** → select the `extension/` folder (same folder for both).
4. Pin "Webflow Bridge" and keep a normal website in the **active tab** —
   `chrome://` pages, the Web Store / Edge Add-ons store and new-tab pages
   cannot be debugged.
5. After editing `manifest.json` or `background.js`, reload the extension —
   unpacked extensions don't hot-apply changes.

**3. Verify** (optional smoke test — prints PASS/FAIL per check, non-zero
exit on failure):

```bash
python3 daemon/smoke.py          # Windows: py -3.11 daemon/smoke.py
```

### Ports & token

| What | Where |
|---|---|
| Chrome/Edge daemon HTTP | `http://127.0.0.1:10086` — `POST /command` |
| Chrome/Edge daemon WebSocket | `ws://127.0.0.1:10087` — the extension connects here |
| Token file | `~/.webflow_bridge/token` (created on first start, mode `0600`) |
| Token via env | `WBF_TOKEN` (or `WBF_TOKEN_FILE` for a custom path) |

The extension bootstraps the token automatically. Your own scripts must send
`Authorization: Bearer <token>` on every POST. `--allow-no-auth` disables auth
and exists **only** as a local migration window — never for daily use.

Daemon flags worth knowing: `--audit PATH` (JSONL audit log),
`--cdp-allowlist METHODS`, `--humanize` (random pacing), `--no-auto-dialog`
(leave native dialogs for explicit `handle_dialog`).

### Keep it running

**macOS — launchd.** From the repo root, one command writes the plist and
hands the daemon to launchd, so it starts at login:

```bash
P=~/Library/LaunchAgents/com.webflow.bridge.plist
mkdir -p ~/Library/LaunchAgents ~/.webflow_bridge
plutil -create xml1 "$P"
plutil -insert Label -string com.webflow.bridge "$P"
plutil -insert ProgramArguments -json "[\"$(command -v python3)\",\"$PWD/daemon/webflow_bridge.py\"]" "$P"
plutil -insert RunAtLoad -bool YES "$P"
plutil -insert KeepAlive -bool YES "$P"
plutil -insert StandardOutPath -string "$HOME/.webflow_bridge/daemon.log" "$P"
plutil -insert StandardErrorPath -string "$HOME/.webflow_bridge/daemon.err" "$P"
launchctl bootstrap gui/$(id -u) "$P"
```

Make sure `command -v python3` resolves to a real 3.11+ (`python3 --version`).
Stop / update / remove:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.webflow.bridge.plist   # stop
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.webflow.bridge.plist # start again
rm ~/Library/LaunchAgents/com.webflow.bridge.plist                               # remove
```

Logs land in `~/.webflow_bridge/daemon.log` and `~/.webflow_bridge/daemon.err`.

**Linux — systemd (user unit).** Adjust `%h/webflow-bridge` if your clone is
elsewhere:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/webflow-bridge.service <<'EOF'
[Unit]
Description=Webflow Bridge daemon
After=network.target

[Service]
WorkingDirectory=%h/webflow-bridge
ExecStart=/usr/bin/python3 %h/webflow-bridge/daemon/webflow_bridge.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now webflow-bridge
```

Check it with `systemctl --user status webflow-bridge` and follow logs with
`journalctl --user -u webflow-bridge -f`. To disable:
`systemctl --user disable --now webflow-bridge`.

### Firefox edition (separate, port `10096`)

Firefox runs through its own daemon over WebDriver BiDi. The core driver needs
**no extension installed** and drives your real daily Firefox profile. Same
action surface, same `POST /command` shape — scripts just point at
`http://127.0.0.1:10096`.

```bash
# 1. open your real profile with BiDi enabled
ff/ff-launch.sh     # macOS (chmod +x first)
ff\ff-launch.bat    # Windows

# 2. start the Firefox daemon
python3 ff/daemon/ff_bridge.py       # macOS: use a real Python 3.11+
py -3.11 ff/daemon/ff_bridge.py      # Windows
```

Token: `~/.webflow_bridge_ff/token` (`0600`), or `WBF_FF_TOKEN`;
`GET http://127.0.0.1:10096/config` returns `{"token": ...}`. BiDi port
defaults to `9222` (`--ff-port`), HTTP to `10096` (`--http-port`).
Full launcher / auth / action-matrix detail: **[../ff/README.md](../ff/README.md)**.

### Uninstall

1. Stop the daemon (Ctrl+C, or the launchd/systemd commands above).
2. Remove the service file if you installed one.
3. Remove the extension in `chrome://extensions` / `edge://extensions`
   (Firefox edition: nothing to remove unless you installed the optional
   toolbar add-on).
4. Delete local state: `rm -rf ~/.webflow_bridge ~/.webflow_bridge_ff`.
5. Delete the repo folder if you no longer want it. No profile, registry or
   system files are touched.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `503 {"error":"extension not connected"}` | Chrome/Edge open? Extension loaded (`chrome://extensions` / `edge://extensions`)? Check the background worker's console for "connected to daemon". |
| evaluate replies "no active tab found" or "chrome:// … cannot be debugged" | The active tab is `chrome://…`, a new-tab page or a store page — none can be debugged. Open a real website in the active tab and retry. |
| evaluate fails with "Another debugger is already attached" | DevTools (or another CDP client) is attached to that tab. Close it and retry. |
| evaluate error mentions "Content Security Policy" | Stale content-script-era build. Fully reload "Webflow Bridge" at `chrome://extensions` (or `edge://extensions`) — current builds evaluate through the debugger channel, which neither page CSP nor the extension CSP can block. |
| Timeout after 120 s | The active tab is busy (modal dialog / blocked script) or the async snippet never resolved — CDP awaits Promise completion values. |
| Port already in use | Another Webflow Bridge instance is running — stop it first. |
| Extension lost connection after a daemon restart | Automatic: reconnects with backoff (up to 30 s); the debugger session re-attaches on the next evaluate — nothing to do. |
| A JS dialog appeared but `handle_dialog` says "no dialog" | Old extension build (Page domain not enabled on attach). Reload the extension at `chrome://extensions`. |
| Clicking an upload button opens the OS "Open File" dialog | Old build without file-chooser interception. Reload the extension, then call `handle_file_chooser` after the click. |

---

## 中文

### 环境要求

- **Python 3.11+** 运行 daemon。全部走标准库 —— 无需 `pip install`。
- **Chrome、Edge 或 Firefox。** Chrome/Edge 用解压加载的 `extension/`；
  Firefox 用 `ff/` 下的独立版。
- **Windows：** 必须用真实的 Python 3.11+ 解释器。Microsoft Store 的
  "python.exe" 是应用执行假桩，会静默出错 —— 请从
  [python.org](https://www.python.org/) 安装，或改用 `uv`。示例命令因此写作
  `py -3.11`。
- **可选：** 装了 [uv](https://astral.sh/uv/) 可跳过系统 Python：
  `uv run --python 3.11 daemon/webflow_bridge.py`。

### Chrome / Edge（macOS · Linux · Windows）

**1. 启动 daemon**（在仓库根目录，二选一）：

```bash
# 直接用 Python
python3 daemon/webflow_bridge.py          # macOS / Linux（Windows 的 Git Bash 亦可）
py -3.11 daemon/webflow_bridge.py         # Windows

# 或装了 uv（任意系统）
uv run --python 3.11 daemon/webflow_bridge.py
```

看到带两个监听端口的横幅即成功：

```
========================================
  Webflow Bridge daemon started
    HTTP  : http://127.0.0.1:10086    POST /command
    WS    : ws://127.0.0.1:10087          Chrome / Edge extension connects here
========================================
```

**2. 加载扩展** —— 一次性、约 30 秒，刻意保持手动（永不自动安装）：

1. Chrome 打开 `chrome://extensions`，Edge 打开 `edge://extensions`。
2. 打开右上角**开发者模式**（两个浏览器开关一致）。
3. **加载已解压的扩展程序** → 选择 `extension/` 文件夹（Chrome/Edge 同一份）。
4. 固定「Webflow Bridge」，并让**活动标签页**停在普通网站上 —— `chrome://` 页、
   商店页和新标签页无法被调试。
5. 改动 `manifest.json` 或 `background.js` 后需重载扩展 —— unpacked 扩展不会热应用修改。

**3. 验证**（可选冒烟测试 —— 逐项打印 PASS/FAIL，失败时非零退出）：

```bash
python3 daemon/smoke.py          # Windows: py -3.11 daemon/smoke.py
```

### 端口与 token

| 项目 | 位置 |
|---|---|
| Chrome/Edge daemon HTTP | `http://127.0.0.1:10086` —— `POST /command` |
| Chrome/Edge daemon WebSocket | `ws://127.0.0.1:10087` —— 扩展连接此处 |
| token 文件 | `~/.webflow_bridge/token`（首次启动生成，权限 `0600`） |
| 环境变量 | `WBF_TOKEN`（或 `WBF_TOKEN_FILE` 指定自定义路径） |

扩展会自动引导拿到 token；你自己的脚本每次 POST 需带
`Authorization: Bearer <token>`。`--allow-no-auth` 会关闭鉴权，**仅**作本地迁移
窗口，不要日常使用。

值得知道的 daemon 参数：`--audit PATH`（JSONL 审计日志）、
`--cdp-allowlist METHODS`、`--humanize`（随机节奏）、`--no-auto-dialog`
（原生弹窗留给显式 `handle_dialog`）。

### 让它常驻

**macOS —— launchd。** 在仓库根目录运行以下命令写入 plist 并交给 launchd，
之后开机即随登录启动：

```bash
P=~/Library/LaunchAgents/com.webflow.bridge.plist
mkdir -p ~/Library/LaunchAgents ~/.webflow_bridge
plutil -create xml1 "$P"
plutil -insert Label -string com.webflow.bridge "$P"
plutil -insert ProgramArguments -json "[\"$(command -v python3)\",\"$PWD/daemon/webflow_bridge.py\"]" "$P"
plutil -insert RunAtLoad -bool YES "$P"
plutil -insert KeepAlive -bool YES "$P"
plutil -insert StandardOutPath -string "$HOME/.webflow_bridge/daemon.log" "$P"
plutil -insert StandardErrorPath -string "$HOME/.webflow_bridge/daemon.err" "$P"
launchctl bootstrap gui/$(id -u) "$P"
```

确认 `command -v python3` 指向真实的 3.11+（`python3 --version`）。
停止 / 重启 / 删除：

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.webflow.bridge.plist   # 停止
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.webflow.bridge.plist # 再次启动
rm ~/Library/LaunchAgents/com.webflow.bridge.plist                               # 删除
```

日志写到 `~/.webflow_bridge/daemon.log` 与 `~/.webflow_bridge/daemon.err`。

**Linux —— systemd（用户级单元）。** 若仓库不在 `~/webflow-bridge`，请相应修改
`%h/webflow-bridge`：

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/webflow-bridge.service <<'EOF'
[Unit]
Description=Webflow Bridge daemon
After=network.target

[Service]
WorkingDirectory=%h/webflow-bridge
ExecStart=/usr/bin/python3 %h/webflow-bridge/daemon/webflow_bridge.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now webflow-bridge
```

用 `systemctl --user status webflow-bridge` 查看状态，`journalctl --user -u
webflow-bridge -f` 跟踪日志。关闭：`systemctl --user disable --now webflow-bridge`。

### Firefox 独立版（端口 `10096`）

Firefox 走自己的 daemon、基于 WebDriver BiDi。核心驱动**无需安装任何扩展**，
驱动的是你日常在用的真实 Firefox profile。动作面与 `POST /command` 形状一致 ——
脚本只需把地址指向 `http://127.0.0.1:10096`。

```bash
# 1. 以 BiDi 模式打开真实 profile
ff/ff-launch.sh     # macOS（先 chmod +x）
ff\ff-launch.bat    # Windows

# 2. 启动 Firefox daemon
python3 ff/daemon/ff_bridge.py       # macOS：用真实 Python 3.11+
py -3.11 ff/daemon/ff_bridge.py      # Windows
```

Token：`~/.webflow_bridge_ff/token`（`0600`），或环境变量 `WBF_FF_TOKEN`；
`GET http://127.0.0.1:10096/config` 返回 `{"token": ...}`。BiDi 端口默认 `9222`
（`--ff-port`），HTTP 默认 `10096`（`--http-port`）。启动器 / 鉴权 / 动作矩阵
完整说明见 **[../ff/README.md](../ff/README.md)**。

### 卸载

1. 停止 daemon（Ctrl+C，或用上面的 launchd / systemd 命令）。
2. 若装过常驻服务，删除对应的服务文件。
3. 在 `chrome://extensions` / `edge://extensions` 移除扩展（Firefox 版除非装过
   可选工具栏附加组件，否则无需移除）。
4. 删除本地状态：`rm -rf ~/.webflow_bridge ~/.webflow_bridge_ff`。
5. 不再需要时删除仓库目录。全程不触碰任何 profile、注册表或系统文件。

### 故障排查

| 症状 | 修复 |
|---|---|
| `503 {"error":"extension not connected"}` | Chrome/Edge 开着吗？扩展加载了吗（`chrome://extensions` / `edge://extensions`）？查后台 worker 控制台有没有 "connected to daemon"。 |
| evaluate 报 "no active tab found" 或 "chrome:// … cannot be debugged" | 活动标签是 `chrome://…`、新标签页或商店页 —— 都不能调试。在活动标签打开真实网站重试。 |
| evaluate 报 "Another debugger is already attached" | 该标签附着着 DevTools（或另一个 CDP 客户端）。关掉再试。 |
| evaluate 报错提到 "Content Security Policy" | content-script 时代的陈旧构建。到 `chrome://extensions`（或 `edge://extensions`）完整重载「Webflow Bridge」—— 当前构建走调试通道，页面 CSP 和扩展 CSP 都拦不住。 |
| 120 s 超时 | 活动标签忙（模态框/脚本阻塞），或 async 片段一直没跑完 —— CDP 会 await Promise 完成值。 |
| 端口被占用 | 另一个实例在跑 —— 先停掉。 |
| daemon 重启后扩展掉线 | 自动恢复：指数退避重连（上限 30 s）；下次 evaluate 自动 re-attach —— 无需操作。 |
| JS 弹窗出现了但 `handle_dialog` 报 no dialog | 旧版扩展（attach 时没开 Page 域）。到 `chrome://extensions` 重载扩展。 |
| 点上传按钮弹系统"打开文件"框 | 旧构建没有文件选择拦截。重载扩展后，click 触发再调 `handle_file_chooser`。 |
