#!/usr/bin/env bash
# push-both.sh — 一键提交并推送到双端 (CNB origin + GitHub 公开仓)
# 用法:
#   tools/push-both.sh "commit message"     # 提交全部改动并推两边
#   tools/push-both.sh --amend "new msg"    # 修改上次提交后推两边
#   tools/push-both.sh --sync               # 不提交, 仅把本地推到两边(拉取同步后)
#   tools/push-both.sh --pull               # 先拉 origin 再推双端(多人协作时用)
#
# 说明: CNB(origin) 直连稳定; GitHub 需外网, 时通时断时重跑 --sync 即可。
#   可选: 配代理后 GitHub 稳定 — git config --global http.https://github.com.proxy http://127.0.0.1:7897
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-}"
if [ "$MODE" = "--sync" ]; then
  echo "[push-both] 仅同步 (git push 双端)"
elif [ "$MODE" = "--pull" ]; then
  echo "[push-both] 先 pull origin/main 再推双端"
  git pull origin main
elif [ "$MODE" = "--amend" ]; then
  MSG="${2:?用法: push-both.sh --amend \"新消息\"}"
  git add -A
  git commit --amend -m "$MSG"
elif [ -n "$MODE" ] && [ "$MODE" != "--amend" ]; then
  MSG="$MODE"
  git add -A
  git commit -m "$MSG"
elif [ -z "$MODE" ]; then
  echo "用法: $0 \"commit message\" | --amend \"msg\" | --sync | --pull"
  exit 1
fi

echo "[push-both] → origin (CNB)"
git push origin main
echo "[push-both] → github (公开)"
git push github main
echo "[push-both] ✅ 双端已同步:"
git log --oneline -1
git remote -v | awk '{print "   ", $1, $2}' | sort -u
