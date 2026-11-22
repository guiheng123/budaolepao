"""Explicit ADB-forwarded smoke test. Spawns Settings, never submits a login."""
import argparse
import json
import threading
import frida
import hook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--addr', default='127.0.0.1:27043')
    parser.add_argument('--app', default='com.android.settings', help='用于验证的应用；测试结束会关闭该进程')
    args = parser.parse_args()
    device = frida.get_device_manager().add_remote_device(args.addr)
    pid = device.spawn([args.app])
    session = None
    done = threading.Event()
    results = []
    errors = []
    try:
        session = device.attach(pid)
        source = hook.build_script(hook.read_cert_hex()[1])
        source += r'''
function verify() { Java.perform(function () {
  try {
    const app = Java.use('android.app.ActivityThread').currentApplication();
    if (app === null) { setTimeout(verify, 100); return; }
    const pm = app.getPackageManager();
    const flags = 0x08000040;
    function snapshot(pkg) {
      const info = pm.getPackageInfo.overload('java.lang.String', 'int').call(pm, pkg, flags);
      return {
        legacy: String(info.signatures.value[0].toCharsString()),
        current: String(info.signingInfo.value.getApkContentsSigners()[0].toCharsString()),
        history: String(info.signingInfo.value.getSigningCertificateHistory()[0].toCharsString())
      };
    }
    const target = snapshot(TARGET);
    const other = snapshot('android');
    send({t: 'verification', targetMatches: target.legacy === HEX && target.current === HEX && target.history === HEX,
          otherUnaffected: other.legacy !== HEX && other.legacy === other.current && other.current === other.history});
  } catch(e) { send({t: 'verification-error', e: String(e), stack: e.stack}); }
}); }
setImmediate(verify);
'''
        def message(message, data):
            print(json.dumps(message, ensure_ascii=False), flush=True)
            payload = message.get('payload', {})
            if message.get('type') == 'error' or payload.get('t') in ('err', 'verification-error'):
                errors.append(message)
            if payload.get('t') in ('verification', 'verification-error'):
                results.append(payload)
                done.set()
        script = session.create_script(source)
        script.on('message', message)
        script.load()
        device.resume(pid)
        if not done.wait(30):
            raise RuntimeError('等待 Java Hook 验证超时')
        if errors or not results or not results[-1].get('targetMatches') or not results[-1].get('otherUnaffected'):
            raise RuntimeError('设备验证失败，见上述消息')
        print('PASS: target signatures replaced; android package signatures unchanged')
    finally:
        if session is not None:
            try:
                session.detach()
            except frida.InvalidOperationError:
                pass
        try:
            device.kill(pid)
        except frida.ProcessNotFoundError:
            pass


if __name__ == '__main__':
    main()
