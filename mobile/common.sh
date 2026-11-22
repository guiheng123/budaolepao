#!/data/data/com.termux/files/usr/bin/bash
# 可覆盖：FRIDA_VERSION、FRIDA_ADDR、FRIDA_SERVER_URL、FRIDA_LOCAL、FRIDA_LOG。
FRIDA_VERSION="${FRIDA_VERSION:-16.7.19}"
FRIDA_ADDR="${FRIDA_ADDR:-127.0.0.1:27042}"
FRIDA_LOCAL="${FRIDA_LOCAL:-/data/local/tmp/frida-server}"
FRIDA_LOG="${FRIDA_LOG:-/data/local/tmp/frida-server.log}"

C_RESET='\033[0m'; C_CYAN='\033[36m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_RED='\033[31m'
log()  { printf "${C_CYAN}[*]${C_RESET} %s\n" "$*"; }
ok()   { printf "${C_GREEN}[+]${C_RESET} %s\n" "$*"; }
warn() { printf "${C_YELLOW}[!]${C_RESET} %s\n" "$*" >&2; }
die()  { printf "${C_RED}[x]${C_RESET} %s\n" "$*" >&2; exit 1; }

in_termux() { [ -d /data/data/com.termux ] || [ -n "${TERMUX_VERSION:-}" ]; }
require_private_workspace() {
  local location
  location="$(cd "$HERE" && pwd -P)" || die "无法解析项目目录"
  case "$location" in
    /sdcard|/sdcard/*|/storage|/storage/*|/mnt/sdcard|/mnt/sdcard/*|/mnt/media_rw|/mnt/media_rw/*|/mnt/runtime|/mnt/runtime/*|/data/media|/data/media/*)
      die "项目位于 Android 共享存储（$location），不能执行 frida-server。请先复制到 Termux 的 \$HOME 私有目录，进入复制后的目录再运行。chmod +x 无法解除共享存储的执行限制。" ;;
  esac
}

# uname reflects the Termux execution architecture, including x86_64 Android VMs.
select_arch() {
  local machine
  machine="$(uname -m)" || die "无法检测架构"
  case "$machine" in
    aarch64|arm64) FRIDA_ARCH=arm64 ;;
    x86_64|amd64) FRIDA_ARCH=x86_64 ;;
    *) die "不支持的架构：$machine（仅支持 arm64 / x86_64 的 64 位 Termux）" ;;
  esac
  FRIDA_SERVER_URL="${FRIDA_SERVER_URL:-https://github.com/frida/frida/releases/download/${FRIDA_VERSION}/frida-server-${FRIDA_VERSION}-android-${FRIDA_ARCH}.xz}"
  ok "Android 架构：$FRIDA_ARCH；Frida 版本：$FRIDA_VERSION"
}

# Quote for Android's root shell, not only for the calling Bash.
shell_quote() { printf "'%s'" "${1//\'/\'\\\'\'}"; }
as_root() { su -c "$1"; }
require_root() {
  if ! as_root id 2>/dev/null | grep -q 'uid=0'; then
    die "su 不可用。请确认设备已 root，并允许 Termux 获得 root。"
  fi
  ok "root 可用"
}

validate_config() {
  [[ "$FRIDA_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "FRIDA_VERSION 必须为 x.y.z"
  [[ "$FRIDA_LOCAL" = /* && "$FRIDA_LOG" = /* && "$FRIDA_LOCAL" != "$FRIDA_LOG" ]] \
    || die "FRIDA_LOCAL / FRIDA_LOG 必须为不同的绝对路径"
  python - "$FRIDA_ADDR" <<'PY' || die "FRIDA_ADDR 必须为 host:port（IPv6 使用 [host]:port）"
import sys
address = sys.argv[1]
try:
    host, port = address.rsplit(':', 1)
    if host.startswith('[') and host.endswith(']'):
        host = host[1:-1]
    elif ':' in host:
        raise ValueError('IPv6 needs brackets')
    if not host or any(c.isspace() for c in host) or not 1 <= int(port) <= 65535:
        raise ValueError('invalid address')
except (ValueError, TypeError):
    raise SystemExit(1)
PY
}

client_version() { python -c 'import frida; print(frida.__version__)' 2>/dev/null; }
require_client() {
  local version
  version="$(client_version)" || die "无法导入 frida-python，请运行 bash $HERE/install.sh（Termux 可能需要自行编译匹配的 Android 扩展）"
  [ "$version" = "$FRIDA_VERSION" ] || die "客户端版本 $version 与要求的 $FRIDA_VERSION 不一致，请重新运行 install.sh"
  ok "frida-python 版本：$version"
}

validate_server() {
  local srv="$1" version
  [ -x "$srv" ] || { warn "server 不存在或不可执行：$srv"; return 1; }
  python - "$srv" "$FRIDA_ARCH" <<'PY' || return 1
import struct, sys
try:
    with open(sys.argv[1], 'rb') as f:
        header = f.read(20)
    expected = {'arm64': 183, 'x86_64': 62}[sys.argv[2]]
    if (len(header) != 20 or header[:6] != b'\x7fELF\x02\x01'
            or struct.unpack('<H', header[18:20])[0] != expected):
        raise ValueError('ELF 架构不匹配，要求 Android ' + sys.argv[2])
except (OSError, ValueError) as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
PY
  version="$("$srv" --version)" || {
    warn "无法执行 $srv --version：这不等于架构/版本不匹配；请检查共享存储 noexec、文件执行权限及系统策略（原始错误见上方）"
    return 1
  }
  [ "$version" = "$FRIDA_VERSION" ] || { warn "server 版本 $version != $FRIDA_VERSION"; return 1; }
}

server_pid() { as_root "pidof $(shell_quote "${FRIDA_LOCAL##*/}")" 2>/dev/null | tr -d '\r' || true; }
show_server_log() {
  warn "server 日志：$FRIDA_LOG（未自动修改 SELinux）"
  as_root "tail -n 60 $(shell_quote "$FRIDA_LOG")" >&2 || true
}

port_open() {
  python - "$FRIDA_ADDR" <<'PY' 2>/dev/null
import socket, sys
host, port = sys.argv[1].rsplit(':', 1)
try:
    with socket.create_connection((host.strip('[]'), int(port)), timeout=1.0):
        pass
except (OSError, ValueError):
    raise SystemExit(1)
PY
}
wait_port() {
  local i=0
  while [ "$i" -lt 20 ]; do
    port_open && return 0
    i=$((i + 1)); sleep 0.3
  done
  warn "连不上 $FRIDA_ADDR"
  return 1
}

check_connection() {
  python - "$FRIDA_ADDR" <<'PY'
import frida, sys
try:
    device = frida.get_device_manager().add_remote_device(sys.argv[1])
    device.enumerate_processes()
except Exception as exc:
    print('Frida 协议连接失败：%s' % exc, file=sys.stderr)
    raise SystemExit(1)
PY
}

start_server() {
  local srv="$1" local_q log_q addr_q version
  validate_server "$srv" || die "本地 server 架构/版本校验失败，请运行 bash $HERE/install.sh"
  local_q="$(shell_quote "$FRIDA_LOCAL")"
  log_q="$(shell_quote "$FRIDA_LOG")"
  addr_q="$(shell_quote "$FRIDA_ADDR")"
  if [ -n "$(server_pid)" ]; then
    version="$(as_root "$local_q --version" 2>/dev/null | tr -d '\r\n')" \
      || die "无法检查已部署 server 版本，请使用 --restart-server 重启"
    [ "$version" = "$FRIDA_VERSION" ] || die "已部署 server 版本不符，请使用 --restart-server 重启"
    ok "frida-server 已在运行（pid $(server_pid)）；检查 $FRIDA_ADDR"
  else
    log "部署 server 并监听 $FRIDA_ADDR；日志：$FRIDA_LOG"
    # Deployment must complete successfully BEFORE putting only the server in background.
    as_root "cp $(shell_quote "$srv") $local_q && chmod 755 $local_q && : > $log_q" \
      || die "部署 server 或创建日志失败"
    as_root "nohup $local_q -l $addr_q </dev/null >>$log_q 2>&1 &" \
      || { show_server_log; die "server 启动命令失败"; }
  fi
  if ! wait_port || [ -z "$(server_pid)" ] || ! check_connection; then
    show_server_log
    die "frida-server 未就绪；请检查日志、root 权限、端口占用及系统策略"
  fi
  ok "frida-server 就绪（pid $(server_pid)），地址 $FRIDA_ADDR"
}
