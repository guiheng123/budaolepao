#!/data/data/com.termux/files/usr/bin/bash
set -eu
set -o pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/common.sh"

RESTART_SERVER=0
ARG=""
for a in "$@"; do
  case "$a" in
    --restart-server) RESTART_SERVER=1 ;;
    1|qq|QQ) ARG="qq" ;;
    2|wechat|WeChat|wx) ARG="wechat" ;;
    -h|--help)
      printf 'usage: bash start.sh [1|2|qq|wechat] [--restart-server]\n'
      printf '环境变量：FRIDA_VERSION FRIDA_ADDR FRIDA_SERVER_URL FRIDA_LOCAL FRIDA_LOG\n'
      printf '支持 Android arm64 / x86_64；不会自动关闭 SELinux。\n'
      exit 0
      ;;
    *) die "未知参数：$a" ;;
  esac
done

if [ -z "$ARG" ]; then
  printf 'Choose target: [1] QQ   [2] WeChat\n'
  printf 'Enter 1 or 2 (blank = 1 QQ): '
  read -r sel || sel=""
  sel="$(printf '%s' "${sel:-1}" | tr -d ' \r\n')"
  case "$sel" in
    1) ARG="qq" ;;
    2) ARG="wechat" ;;
    *) die "只能输入 1 或 2" ;;
  esac
fi

printf '\n=== 步道乐跑 手机端一键 Hook · %s ===\n\n' "$ARG"

in_termux || die "请在 Android 的 Termux 中运行本脚本"
require_private_workspace
command -v python >/dev/null 2>&1 || die "缺少 python，请先运行 install.sh"
select_arch
validate_config
require_client
[ -f "$HERE/hook.py" ] || die "缺少 hook.py"
[ -f "$HERE/hook/spoof.template.js" ] || die "缺少 hook/spoof.template.js"

require_root

SRV="$HERE/bin/frida-server"
if [ "$RESTART_SERVER" = "1" ]; then
  log "按要求重启 frida-server"
  PIDS="$(server_pid)"
  if [ -n "$PIDS" ]; then
    [[ "$PIDS" =~ ^[0-9]+([[:space:]][0-9]+)*$ ]] || die "server PID 格式异常：$PIDS"
    as_root "kill $PIDS" || die "无法停止 frida-server"
    for ((i=0; i<20; i++)); do
      [ -z "$(server_pid)" ] && break
      sleep 0.3
    done
    [ -z "$(server_pid)" ] || die "server 未停止，拒绝覆盖仍在运行的文件"
  fi
fi

start_server "$SRV"

printf '\n提示：\n'
printf '  · 保持这个窗口开着（Ctrl-C 结束）\n'
if [ "$ARG" = "qq" ]; then
  printf '  · 现在去点：步道乐跑 → 登录 → QQ登录 → 授权页「同意」\n'
else
  printf '  · 先把微信从后台划掉（强停），再点：步道乐跑 → 登录 → 微信登录 → 「同意」\n'
fi
printf '  · 看到 patch 输出即签名已替换，此后不退出登录就不必再开\n\n'

exec python -u "$HERE/hook.py" --target "$ARG" --addr "$FRIDA_ADDR"