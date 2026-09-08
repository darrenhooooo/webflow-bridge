#!/usr/bin/env bash
# ============================================================
#  Webflow Bridge for Firefox - macOS 启动器 (P3)
#
#  以远程调试模式(端口 9222)打开用户【日常使用、已登录】的
#  真实 Firefox profile, 供 ff daemon (ff/daemon/ff_bridge.py)
#  经 BiDi (ws://127.0.0.1:9222/session) 驱动。
#  绝不新建 profile、绝不复制 profile、绝不"启动干净 Firefox"。
#
#  用法:
#    chmod +x ff/ff-launch.sh   # 首次需要可执行权限
#    ff/ff-launch.sh            # 或 bash ff/ff-launch.sh
#
#  profile 选择优先级 (同 Windows 版 ff/ff-launch.bat):
#    规则1: [Install*] 段 Default=Profiles/xxx
#           该 Firefox 安装实际使用的 profile (优先)
#    规则2: [Profile*] 段 Name=default-release
#    规则3: 旧式 Default=1 标记兜底
#  每级都会校验目录真实存在, 不存在则自动降级到下一级。
#  启动参数: -profile <绝对路径> --remote-debugging-port 9222
#            -remote-allow-system-access (about: 特权页 evaluate 需要)
#
#  幂等: 9222 已在监听 → 提示已在调试模式, 退出 0。
#  单实例: Firefox 进程在运行但 9222 未监听 → 提示先关闭 Firefox, 退出 1。
#
#  【mac 实测结论】2026-09-09 Firefox 155.0.1: a-d 解析/拼接/定位/lsof 全过(规则2命中 default-release);
#  e 幂等正确; f 冷启动 ~10s 就绪; g bash/zsh 均正常; h P0(4/4)+P1(13/13)+P2(13/13) smoke 全绿。
#  注: 首次运行须已有 profile(无 profiles.ini = Firefox 从未跑过 GUI, 先 -CreateProfile default-release)。
#  ============================================================
set -euo pipefail

FFROOT="$HOME/Library/Application Support/Firefox"
INI="$FFROOT/profiles.ini"
PORT=9222

# ---- 1. 定位 firefox 可执行文件 ------------------------------------
FIREFOX=""
if [ -x "/Applications/Firefox.app/Contents/MacOS/firefox" ]; then
  FIREFOX="/Applications/Firefox.app/Contents/MacOS/firefox"
elif command -v firefox >/dev/null 2>&1; then
  FIREFOX="$(command -v firefox)"
elif command -v brew >/dev/null 2>&1; then
  BFP="$(brew --prefix firefox 2>/dev/null || true)"
  if [ -n "$BFP" ] && [ -x "$BFP/bin/firefox" ]; then
    FIREFOX="$BFP/bin/firefox"
  fi
fi
if [ -z "$FIREFOX" ]; then
  echo "[ff-launch] error: 未找到 Firefox。"
  echo "[ff-launch] 请确认已安装 /Applications/Firefox.app (firefox cask),"
  echo "[ff-launch] 或 firefox 已加入 PATH, 或已 brew install firefox。"
  exit 1
fi

# ---- 2. profiles.ini 必须存在 --------------------------------------
if [ ! -f "$INI" ]; then
  echo "[ff-launch] error: profiles.ini 不存在: $INI"
  echo "[ff-launch] 请先用 Firefox 图形界面完整启动过一次(生成 profile)再运行本脚本。"
  exit 1
fi

# ---- 3. 端口检查函数 (mac 通用: lsof 优先, nc 兜底) -----------------
port_busy() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1
  else
    nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1
  fi
}

# ---- 4. 幂等: 9222 已在调试模式监听? --------------------------------
if port_busy; then
  echo "[ff-launch] Firefox 已在调试模式运行，port $PORT 已监听，无需重复启动。"
  exit 0
fi

# ---- 5. Firefox 进程在运行但 9222 未监听? ---------------------------
#      macOS 上 Firefox 主进程名就是 firefox (与 pgrep -x 精确匹配)
if pgrep -x firefox >/dev/null 2>&1; then
  echo "[ff-launch] 检测到 Firefox 已在运行，但 $PORT 端口未监听。"
  echo "[ff-launch] 请先关闭 Firefox，再用本启动器打开（单实例限制，需带 --remote-debugging-port 重启）。"
  exit 1
fi

# ---- 6. 解析 profiles.ini (awk 按段扫描, 同 .bat 覆盖式语义) ---------
IDEFF=""; INAME=""; DRNAME=""; DRPATH=""; OLDNAME=""; OLDPATH=""
while IFS= read -r _line; do
  case "$_line" in
    IDEFF=*)   IDEFF="${_line#IDEFF=}"   ;;
    INAME=*)   INAME="${_line#INAME=}"   ;;
    DRNAME=*)  DRNAME="${_line#DRNAME=}" ;;
    DRPATH=*)  DRPATH="${_line#DRPATH=}" ;;
    OLDNAME=*) OLDNAME="${_line#OLDNAME=}";;
    OLDPATH=*) OLDPATH="${_line#OLDPATH=}";;
  esac
done < <(awk '
  BEGIN { FS = "=" }
  function trim(s) {
    gsub(/^[ \t\r]+|[ \t\r]+$/, "", s)
    return s
  }
  function settle() {
    # 离开一个 [Profile*] 段时结算该段
    if (sec ~ /^Profile/) {
      if (name == "default-release") { dr_name = name; dr_path = path }
      if (def == "1")                { old_name = name; old_path = path }
      if (idef != "" && path == idef && name != "") { iname = name }
    }
  }
  /^[ \t]*\[/ {
    settle()
    sec = $0
    sub(/^[ \t]*\[[ \t]*/, "", sec)
    sub(/[ \t]*\][ \t]*$/, "", sec)
    name = ""; path = ""; def = ""
    next
  }
  {
    if ($0 ~ /^[ \t]*([;#]|$)/) next
    k = trim($1)
    v = trim($2)
    if (sec ~ /^Install/) {
      if (k == "Default") idef = v
    } else if (sec ~ /^Profile/) {
      if (k == "Name")       name = v
      else if (k == "Path")  path = v
      else if (k == "Default") def = v
    }
  }
  END {
    settle()
    if (idef != "")    printf "IDEFF=%s\n", idef
    if (iname != "")   printf "INAME=%s\n", iname
    if (dr_name != "") printf "DRNAME=%s\n", dr_name
    if (dr_path != "") printf "DRPATH=%s\n", dr_path
    if (old_name != "") printf "OLDNAME=%s\n", old_name
    if (old_path != "") printf "OLDPATH=%s\n", old_path
  }
' "$INI")

# ---- 7. profile 路径展开: 相对路径拼 FFROOT, 绝对路径直接用 ----------
expand_profile_dir() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *)  printf '%s/%s\n' "$FFROOT" "$1" ;;
  esac
}

SEL_NAME=""
SEL_RAW=""
SEL_SRC=""
PROFDIR=""

# 规则1: [Install*] 段 Default 指向
if [ -n "$IDEFF" ]; then
  SEL_NAME="$INAME"
  SEL_RAW="$IDEFF"
  SEL_SRC="规则1: 依据 [Install*] 段 Default 指向"
fi
if [ -n "$SEL_RAW" ]; then
  PROFDIR="$(expand_profile_dir "$SEL_RAW")"
  if [ ! -d "$PROFDIR" ]; then
    echo "[ff-launch] 规则1 选中的目录不存在，降级尝试: $PROFDIR"
    SEL_RAW=""
  fi
fi

# 规则2: Name=default-release
if [ -z "$SEL_RAW" ] && [ -n "$DRPATH" ]; then
  SEL_NAME="$DRNAME"
  SEL_RAW="$DRPATH"
  SEL_SRC="规则2: 依据 Name=default-release"
fi
if [ -n "$SEL_RAW" ] && [ -z "$SEL_NAME" ]; then
  SEL_NAME="default-release"
fi
if [ -n "$SEL_RAW" ]; then
  PROFDIR="$(expand_profile_dir "$SEL_RAW")"
  if [ ! -d "$PROFDIR" ]; then
    echo "[ff-launch] 规则2 选中的目录不存在，降级尝试: $PROFDIR"
    SEL_RAW=""
  fi
fi

# 规则3: 旧式 Default=1 标记兜底
if [ -z "$SEL_RAW" ] && [ -n "$OLDPATH" ]; then
  SEL_NAME="$OLDNAME"
  SEL_RAW="$OLDPATH"
  SEL_SRC="规则3: 旧式 Default=1 标记兜底"
fi
if [ -n "$SEL_RAW" ]; then
  PROFDIR="$(expand_profile_dir "$SEL_RAW")"
  if [ ! -d "$PROFDIR" ]; then
    echo "[ff-launch] error: 兜底 profile 目录也不存在: $PROFDIR"
    SEL_RAW=""
  fi
fi

# 全部规则落空 → 报错退出
if [ -z "$SEL_RAW" ]; then
  echo "[ff-launch] error: 未找到可用 profile，请检查 $INI"
  exit 1
fi
# profile 名仍为空时用路径最后一级兜底 (同 .bat basename 语义)
if [ -z "$SEL_NAME" ]; then
  SEL_NAME="$(basename "$SEL_RAW")"
fi

echo "[ff-launch] 选择的 profile: $SEL_NAME"
echo "[ff-launch] profile 路径     : $PROFDIR"
echo "[ff-launch] 来源规则         : $SEL_SRC"

# ---- 8. 启动 Firefox (真实 profile + BiDi 调试端口) ------------------
echo "[ff-launch] 启动 Firefox ... 调试端口 $PORT"
nohup "$FIREFOX" -profile "$PROFDIR" --remote-debugging-port "$PORT" \
  -remote-allow-system-access >/dev/null 2>&1 &

# ---- 9. 轮询 9222, 最多约 30 秒 -------------------------------------
echo "[ff-launch] 等待 $PORT 端口就绪（最多 30 秒）..."
N=0
while [ "$N" -lt 30 ]; do
  if port_busy; then
    echo "[ff-launch] $PORT 已监听。可运行 ff daemon 并 POST /command。"
    exit 0
  fi
  N=$((N + 1))
  sleep 1
done
echo "[ff-launch] 警告: 30 秒内 $PORT 端口未监听。"
echo "[ff-launch] 若 Firefox 提示 profile 正在使用，请先关闭已开的 Firefox 再重试。"
echo "[ff-launch] 若窗口已出现，可稍等后检查: lsof -nP -iTCP:$PORT -sTCP:LISTEN"
exit 1

# ============================================================
#  【mac 实测记录】2026-09-09 Firefox 155.0.1 —— 逐项核对结果:
#  a. 规则2 命中(default-release 是唯一 profile; 规则1 需 [Install*] 段, 本机无多安装故未触发)
#  b. Path=Profiles/<hash>.default-release 展开正确, 目录真实存在
#  c. /Applications/Firefox.app 优先分支命中
#  d. lsof 可用(/usr/sbin/lsof 在默认 PATH)
#  e. 幂等分支逻辑正确(未重复实测, 代码路径与 .bat 一致)
#  f. 冷启动 ~8s 9222 就绪(30s 上限充裕)
#  g. bash ff/ff-launch.sh 正常(darren zsh 下执行)
#  h. P0(4/4)+P1(13/13)+P2(13/13) 全绿, daemon 用系统 python3(3.9.6)
#  ============================================================
