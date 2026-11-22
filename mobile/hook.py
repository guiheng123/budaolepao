#!/usr/bin/env python3
"""Local/remote Frida client for the mobile signature hook."""
import argparse
import os
import sys
import threading
import time

try:
    import frida
except ImportError:
    frida = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEMPLATE = os.path.join(HERE, 'hook', 'spoof.template.js')
CERT_CANDIDATES = [os.path.join(HERE, 'official_cert.der'),
                   os.path.join(ROOT, 'tools', 'official_cert.der')]
DEFAULT_ADDR = os.environ.get('FRIDA_ADDR', '127.0.0.1:27042')
TARGET_PROCS = {'qq': ['com.tencent.mobileqq:openSdk'], 'wechat': ['com.tencent.mm']}


def build_script(cert_hex):
    if not cert_hex or len(cert_hex) % 2:
        raise ValueError('证书 hex 为空或长度不是偶数')
    bytes.fromhex(cert_hex)
    with open(TEMPLATE, encoding='utf-8') as stream:
        source = stream.read()
    if source.count('__CERT_HEX__') != 1:
        raise ValueError('模板必须且只能包含一个 __CERT_HEX__ 占位符')
    return source.replace('__CERT_HEX__', cert_hex)


def read_cert_hex():
    for path in CERT_CANDIDATES:
        if os.path.isfile(path):
            with open(path, 'rb') as stream:
                data = stream.read()
            if not data:
                raise ValueError('证书文件为空：%s' % path)
            return path, data.hex()
    raise FileNotFoundError('找不到 official_cert.der（试过：%s）' % ', '.join(CERT_CANDIDATES))


def connect(addr):
    manager = frida.get_device_manager()
    device = manager.add_remote_device(addr)
    try:
        device.enumerate_processes()
    except Exception:
        manager.remove_remote_device(addr)
        raise
    return device


def cleanup(sessions):
    for session, script, detached in list(sessions.values()):
        try:
            session.detach()
        except Exception:
            pass
    sessions.clear()


def positive(value):
    number = float(value)
    if not 0 < number < float('inf'):
        raise argparse.ArgumentTypeError('必须为有限正数')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description='手机端 Frida 签名 Hook 客户端')
    parser.add_argument('--target', choices=sorted(TARGET_PROCS), default='qq')
    parser.add_argument('--addr', default=DEFAULT_ADDR)
    parser.add_argument('--proc', action='append', help='精确进程名，可重复；覆盖 target 默认进程')
    parser.add_argument('--interval', type=positive, default=0.5, help='轮询间隔秒数')
    parser.add_argument('--duration', type=positive, help='运行指定秒数后清理退出，方便调试')
    parser.add_argument('--output', help='仅生成可独立注入的 JS，无需安装 frida-python')
    args = parser.parse_args(argv)
    try:
        cert_path, cert_hex = read_cert_hex()
        source = build_script(cert_hex)
    except (OSError, ValueError) as error:
        parser.exit(1, '错误：%s\n' % error)
    if args.output:
        with open(args.output, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(source)
        print('[+] 已生成 %s' % args.output)
        return 0
    if frida is None:
        parser.exit(1, '缺少 frida-python，请先运行 bash install.sh\n')

    processes = args.proc or TARGET_PROCS[args.target]
    print('[+] 证书：%s（%d 字节）' % (cert_path, len(cert_hex) // 2), flush=True)
    print('[+] 目标进程：%s；地址：%s' % (', '.join(processes), args.addr), flush=True)
    device = None
    sessions = {}
    deadline = time.monotonic() + args.duration if args.duration else None
    retry_at = {}
    status = 0
    try:
        while deadline is None or time.monotonic() < deadline:
            try:
                if device is None:
                    device = connect(args.addr)
                    print('[+] 已连接 %s，等待 %s 出现 ...' % (args.addr, ' / '.join(processes)), flush=True)
                current = {p.pid: p.name for p in device.enumerate_processes()}
                for pid in list(sessions):
                    if pid not in current or sessions[pid][2].is_set():
                        entry = {pid: sessions.pop(pid)}
                        cleanup(entry)
                        print('[-] 已脱离 pid %d，等待重新挂载' % pid, flush=True)
                for pid in list(retry_at):
                    if pid not in current:
                        retry_at.pop(pid)
                for pid, name in current.items():
                    if name not in processes or pid in sessions or time.monotonic() < retry_at.get(pid, 0):
                        continue
                    session = None
                    try:
                        session = device.attach(pid)
                        detached = threading.Event()
                        session.on('detached', lambda *unused, event=detached: event.set())
                        script = session.create_script(source)
                        script.on('message', lambda message, data, label='%s:%d' % (name, pid):
                                  print('[%s] %s' % (label, message.get('payload', message)), flush=True))
                        script.load()
                        sessions[pid] = (session, script, detached)
                        retry_at.pop(pid, None)
                        print('>>> 已注入 %s (pid %d)，以 ready/err 消息判断 Hook 安装结果' % (name, pid), flush=True)
                    except Exception as error:
                        if session is not None:
                            try:
                                session.detach()
                            except Exception:
                                pass
                        retry_at[pid] = time.monotonic() + 2
                        print('[!] attach 失败 pid=%d: %s' % (pid, error), flush=True)
            except Exception as error:
                print('[!] 连接/轮询异常：%s（稍后重连）' % error, flush=True)
                cleanup(sessions)
                device = None
                try:
                    frida.get_device_manager().remove_remote_device(args.addr)
                except Exception:
                    pass
            delay = args.interval if device is not None else max(1, args.interval)
            if deadline is not None:
                delay = min(delay, max(0, deadline - time.monotonic()))
            time.sleep(delay)
    except KeyboardInterrupt:
        print('\n[+] 收到退出请求', flush=True)
    finally:
        cleanup(sessions)
        try:
            frida.get_device_manager().remove_remote_device(args.addr)
        except Exception:
            pass
        print('[+] 已清理注入会话（server 保持运行）', flush=True)
    return status


if __name__ == '__main__':
    sys.exit(main())
