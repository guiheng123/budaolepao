"""常驻脚本：QQ 的 :openSdk 进程一出现就挂签名伪造 hook，让 QQ 认为 com.lptiyu.tanke 是官方正版。

用法（在脱壳目录下）：
    python tools/wait_opensdk.py
也可用 tools/start_qq_hook.ps1 一键完成 adb root / frida-server / 本脚本。
本脚本只做最后一件事：轮询 127.0.0.1:27042 上的 frida，等 :openSdk 进程出现即 attach 并注入 hook。
"""
import os
import sys
import time

import frida

HERE = os.path.dirname(os.path.abspath(__file__))
CERT_FILE = os.path.join(HERE, 'official_cert.der')
TARGET_PROC = 'com.tencent.mobileqq:openSdk'
TARGET_PKG = 'com.lptiyu.tanke'
FRIDA_ADDR = '127.0.0.1:27042'

JS = r'''
const HEX = 'CERT_HEX_PLACEHOLDER';
const TARGET = 'TARGET_PKG';
const bytes = [];
for (let i = 0; i + 1 < HEX.length; i += 2) {
  let v = parseInt(HEX.substr(i, 2), 16);
  if (v > 127) v -= 256;
  bytes.push(v);
}

Java.perform(function () {
  const Signature = Java.use('android.content.pm.Signature');
  const official = Signature.$new(bytes);
  const SigArr = Java.array('android.content.pm.Signature', [official]);

  function fix(pi, where) {
    if (!pi) return pi;
    try {
      pi.signatures.value = SigArr;
      send({ t: 'patch', where: where });
    } catch (e) { send({ t: 'err', where: where, e: e.message }); }
    return pi;
  }

  send({ t: 'ready' });

  // 1) getPackageInfo(String, int|PackageInfoFlags)：QQ 查 com.lptiyu.tanke 签名走这里
  const PM = Java.use('android.app.ApplicationPackageManager');
  ['getPackageInfo', 'getPackageInfoAsUser'].forEach(function (m) {
    try {
      PM[m].overloads.forEach(function (ov) {
        if (ov.argumentTypes.length !== 2) return;
        if (ov.argumentTypes[0].className !== 'java.lang.String') return;
        if (!/int|PackageInfoFlags/.test(ov.argumentTypes[1].className)) return;
        ov.implementation = function (pkg, flags) {
          const r = ov.call(this, pkg, flags);
          if (pkg === TARGET) fix(r, m + '(' + ov.argumentTypes[1].className + ')');
          return r;
        };
        send({ t: 'hook', what: m + '(' + ov.argumentTypes[1].className + ')' });
      });
    } catch (e) { send({ t: 'err', what: m, e: e.message }); }
  });

  // 2) SigningInfo 兜底（API 28+ 走这里取签名）
  try {
    const SI = Java.use('android.content.pm.SigningInfo');
    SI.getApkContentsSigners.implementation = function () { return SigArr; };
    SI.getSigningCertificateHistory.implementation = function () { return SigArr; };
    send({ t: 'hook', what: 'SigningInfo' });
  } catch (e) { send({ t: 'err', what: 'SigningInfo', e: e.message }); }

  // 3) getInstalledPackages 兜底（批量查包后比对签名的实现）
  try {
    PM.getInstalledPackages.overload('int').implementation = function (flags) {
      const list = this.getInstalledPackages(flags);
      for (let i = 0; i < list.size(); i++) {
        const pi = list.get(i);
        if (pi.packageName.value === TARGET) fix(pi, 'getInstalledPackages');
      }
      return list;
    };
    send({ t: 'hook', what: 'getInstalledPackages' });
  } catch (e) { send({ t: 'err', what: 'getInstalledPackages', e: e.message }); }
});
'''


def build_script(cert_hex):
    return JS.replace('CERT_HEX_PLACEHOLDER', cert_hex).replace('TARGET_PKG', TARGET_PKG)


def main():
    if not os.path.exists(CERT_FILE):
        print('缺少证书文件:', CERT_FILE, flush=True)
        return 1
    cert_hex = open(CERT_FILE, 'rb').read().hex()

    dev = frida.get_device_manager().add_remote_device(FRIDA_ADDR)
    print('连上 frida %s，等待 %s 出现 ...' % (FRIDA_ADDR, TARGET_PROC), flush=True)

    hooked = {}
    while True:
        try:
            procs = {p.pid: p.name for p in dev.enumerate_processes()}
            for pid, name in procs.items():
                if name != TARGET_PROC or pid in hooked:
                    continue
                try:
                    session = dev.attach(pid)
                    sc = session.create_script(build_script(cert_hex))
                    sc.on('message', lambda m, d: print('[openSdk]', m.get('payload', m), flush=True))
                    sc.load()
                    hooked[pid] = session
                    print('>>> 已挂 hook: %s (pid %d)' % (name, pid), flush=True)
                except Exception as e:
                    print('attach 失败', pid, e, flush=True)
            for pid in list(hooked):
                if pid not in procs:
                    hooked.pop(pid, None)
        except Exception as e:
            print('轮询异常:', e, flush=True)
        time.sleep(0.5)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('exit')
