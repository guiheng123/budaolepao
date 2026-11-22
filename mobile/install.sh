#!/data/data/com.termux/files/usr/bin/bash
set -eu
set -o pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/common.sh"

printf '\n=== 步道乐跑 Termux 环境安装（arm64 / x86_64）===\n\n'
in_termux || die "请在 Android 的 Termux 中运行本脚本"
require_private_workspace
select_arch

log "安装/更新基础依赖：python python-pip curl xz-utils coreutils"
command -v pkg >/dev/null 2>&1 || die "缺少 Termux pkg"
pkg update -y || die "pkg update 失败，请检查 Termux 软件源和网络"
pkg install -y python python-pip curl xz-utils coreutils || die "基础依赖安装失败"
for c in python curl xz od awk su; do
  command -v "$c" >/dev/null 2>&1 || die "缺少命令：$c"
done
validate_config
require_root
mkdir -p "$HERE/bin"
SRV="$HERE/bin/frida-server"
if ! validate_server "$SRV"; then
  log "下载 frida-server ${FRIDA_VERSION}（android-${FRIDA_ARCH}）：$FRIDA_SERVER_URL"
  # Use private temporary paths and preserve the old binary until validation succeeds.
  STAGE="$(mktemp -d "$HERE/bin/.frida-download.XXXXXX")" || die "无法创建下载临时目录"
  trap 'rm -rf -- "$STAGE"' EXIT
  curl -fL --retry 3 -o "$STAGE/server.xz" "$FRIDA_SERVER_URL" \
    || die "server 下载失败，请检查 FRIDA_SERVER_URL / FRIDA_VERSION"
  xz -dc "$STAGE/server.xz" > "$STAGE/frida-server" || die "server 解压失败"
  chmod 755 "$STAGE/frida-server" || die "server chmod 失败"
  validate_server "$STAGE/frida-server" || die "下载的 server 校验失败，请根据上方错误区分架构、版本和执行权限问题"
  mv -f "$STAGE/frida-server" "$SRV" || die "无法保存 server"
  rm -rf -- "$STAGE"
  trap - EXIT
fi
ok "frida-server 就绪：$SRV"

if [ "$(client_version || true)" != "$FRIDA_VERSION" ]; then
  log "安装 frida-python ${FRIDA_VERSION}（Termux 无匹配 wheel 时可能需要源码构建）"
  PIP_LOG="$HERE/bin/pip-frida.log"
  python -m pip --version >/dev/null 2>&1 || die "缺少 pip，请先 pkg install python-pip"
  if ! python -m pip install --no-cache-dir --no-input "frida==${FRIDA_VERSION}" >"$PIP_LOG" 2>&1; then
    warn "pip 安装失败，日志：$PIP_LOG"
    tail -n 40 "$PIP_LOG" >&2 || true
    warn "尝试官方 core-devkit + Python 扩展本地编译（绕过缺失的 Android 预编译工具链）"
    pkg install -y clang make pkg-config || die "安装编译依赖失败"
    python -m pip install --no-input setuptools wheel || die "安装 Python 打包依赖失败"
    [ -f "$HERE/build_frida.py" ] || die "缺少 build_frida.py，请更新完整 mobile 目录"
    FRIDA_VERSION="$FRIDA_VERSION" python "$HERE/build_frida.py" >"$HERE/bin/build-frida.log" 2>&1 || {
      tail -n 60 "$HERE/bin/build-frida.log" >&2 || true
      die "本地构建失败，完整日志：$HERE/bin/build-frida.log"
    }
    ok "官方 devkit 本地构建成功"
  fi
fi
require_client

CERT="$HERE/official_cert.der"
[ -f "$CERT" ] || CERT="$(dirname "$HERE")/tools/official_cert.der"
[ -s "$CERT" ] || die "找不到非空 official_cert.der（应位于 mobile/ 或 tools/ 下）"
[ -f "$HERE/hook/spoof.template.js" ] || die "缺少 hook/spoof.template.js，请补齐项目文件"
ok "官方证书：$CERT（$(wc -c <"$CERT" | tr -d ' ') 字节）"
HEX="$(od -An -v -tx1 "$CERT" | tr -d ' \n\r')"
printf '%s' "$HEX" > "$HERE/hook/cert.hex"
awk -v hex="$HEX" '{ gsub(/__CERT_HEX__/, hex); print }' "$HERE/hook/spoof.template.js" \
  > "$HERE/hook/signature-spoof.js"
ok "已生成 hook/signature-spoof.js"

start_server "$SRV"
printf '\n=== 安装完成 ===\n'
printf '下一步：\n  cd %s && bash start.sh  # 交互选 1=QQ / 2=微信\n' "$HERE"
printf '请在后续运行中保留相同的 FRIDA_VERSION / FRIDA_ADDR 等环境变量覆盖。\n'
