#!/usr/bin/env bash
export DEEPSEEK_API_KEY="$(grep -E '^DEEPSEEK_API_KEY=' "C:/Users/darre/AppData/Local/hermes/profiles/gplp_douzi/.env" 2>/dev/null | head -1 | cut -d= -f2-)"
if [ -z "$DEEPSEEK_API_KEY" ]; then
  export DEEPSEEK_API_KEY="$(grep -E '^DEEPSEEK_API_KEY=' "$HOME/.hermes/.env" 2>/dev/null | head -1 | cut -d= -f2-)"
fi
cd /c/Users/darre/webflow
pi --provider deepseek --model deepseek-v4-flash --no-session --print "$(cat .pi_phaseB_task.txt)"
