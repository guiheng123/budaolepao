#!/usr/bin/env python3
"""Build the official Python extension against the matching Android core devkit."""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import urllib.request


IMPORT_CHECK = (
    'import importlib.util,sys; s=importlib.util.spec_from_file_location("_frida",sys.argv[1]); '
    'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
    'assert m.__version__ == sys.argv[2]; print("NATIVE_EXTENSION_OK",m.__version__)'
)
IMPORT_FRIDA = 'import frida; print("FRIDA_PYTHON_OK", frida.__version__)'
SYMBOL_HINT = (
    '导入失败：_frida.abi3.so 找不到 CPython 符号（cannot locate symbol）。'
    '请确认 Termux 的 python 与 libpython 版本一致，并运行 pkg install patchelf 后重试'
)


def download(url, destination):
    print('[*] 下载 ' + url, flush=True)
    temporary = destination.with_suffix(destination.suffix + '.part')
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
        shutil.copyfileobj(response, output)
    temporary.replace(destination)


def libpython_link_flags():
    """让 _frida.abi3.so 显式依赖 libpython。

    Android 的 linker 不会像桌面 Linux 那样把主程序的符号暴露给 dlopen 进来的模块，
    Termux 的 CPython 把解释器符号放在 libpythonX.Y.so 里；扩展模块不记录这条依赖时，
    dlopen 会报 ``cannot locate symbol "_Py_NoneStruct"``。
    """
    libdir = sysconfig.get_config_var('LIBDIR') or ''
    ldlib = sysconfig.get_config_var('LDLIBRARY') or ''
    instsoname = sysconfig.get_config_var('INSTSONAME') or ldlib
    if not libdir or not ldlib.startswith('libpython') or not (Path(libdir) / ldlib).exists():
        print('[!] 没找到 libpython 共享库，跳过显式链接；若导入报 _Py_NoneStruct 请安装 patchelf 后重试', flush=True)
        return [], None
    # libpython3.14.so -> -lpython3.14
    link = ['-Wl,--no-as-needed', '-L' + libdir, '-l' + ldlib.split('.so')[0][len('lib'):],
            '-Wl,-rpath,' + libdir]
    print('[*] 链接 libpython：' + str(Path(libdir) / ldlib), flush=True)
    return link, instsoname


def verify_extension(path, version):
    return subprocess.run([sys.executable, '-c', IMPORT_CHECK, str(path), version],
                          text=True, capture_output=True)


def add_libpython_dependency(path, soname):
    """用 patchelf 给已生成的 .so 补 DT_NEEDED；patchelf 不可用时返回 False。"""
    patchelf = shutil.which('patchelf')
    if not patchelf or not soname:
        return False
    try:
        needed = subprocess.run([patchelf, '--print-needed', str(path)],
                                text=True, capture_output=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        needed = []
    if soname in needed:
        return True
    args = [patchelf, '--add-needed', soname]
    libdir = sysconfig.get_config_var('LIBDIR') or ''
    if libdir:
        args += ['--add-rpath', libdir]
    args.append(str(path))
    try:
        subprocess.run(args, check=True, text=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print('[!] patchelf 处理失败：%s' % exc, flush=True)
        return False
    print('[+] 已补上依赖：' + soname, flush=True)
    return True


def installed_extension():
    for key in ('platlib', 'purelib'):
        root = sysconfig.get_path(key)
        if not root:
            continue
        candidate = Path(root) / 'frida' / '_frida.abi3.so'
        if candidate.exists():
            return candidate
    return None


def main():
    if sysconfig.get_config_var('Py_GIL_DISABLED'):
        raise RuntimeError('此构建路径不支持 free-threaded Python，请使用标准带 GIL 的 CPython')
    version = os.environ.get('FRIDA_VERSION', '16.7.19')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid FRIDA_VERSION')
    arch = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'x86_64'}.get(platform.machine())
    if arch is None:
        raise RuntimeError('Unsupported architecture: ' + platform.machine())
    work = Path(__file__).resolve().parent / 'bin' / ('native-' + version + '-' + arch)
    work.mkdir(parents=True, exist_ok=True)
    source_archive = work / 'source.tar.gz'
    devkit_archive = work / 'devkit.tar.xz'
    if not source_archive.exists():
        with urllib.request.urlopen('https://pypi.org/pypi/frida/' + version + '/json', timeout=60) as response:
            metadata = json.load(response)
        url = next(item['url'] for item in metadata['urls'] if item['packagetype'] == 'sdist')
        download(url, source_archive)
    if not devkit_archive.exists():
        download('https://github.com/frida/frida/releases/download/' + version +
                 '/frida-core-devkit-' + version + '-android-' + arch + '.tar.xz', devkit_archive)
    source_root = work / 'source'
    devkit = work / 'devkit'
    for archive, destination in ((source_archive, source_root), (devkit_archive, devkit)):
        destination.mkdir(exist_ok=True)
        with tarfile.open(archive) as package:
            package.extractall(destination, filter='data')
    source = source_root / ('frida-' + version)
    extension = work / '_frida.abi3.so'
    link_flags, libpython = libpython_link_flags()
    command = ['clang', '-shared', '-fPIC', '-O2', '-DANDROID', '-DPy_LIMITED_API=0x03070000',
               '-I' + sysconfig.get_path('include'), '-I' + str(devkit),
               str(source / 'frida/_frida/extension.c'), '-L' + str(devkit)]
    # Some x86_64 VMs translate an ARM64 Termux. Never link their x86_64 libc.
    expected_machine = {'arm64': 183, 'x86_64': 62}[arch]
    translated_libraries = Path('/system/lib64/arm64')
    if arch == 'arm64' and (translated_libraries / 'libc.so').exists():
        header = (translated_libraries / 'libc.so').read_bytes()[:20]
        if header[:4] == b'\x7fELF' and int.from_bytes(header[18:20], 'little') == expected_machine:
            command.append('-L' + str(translated_libraries))
    command += link_flags
    command += ['-lfrida-core', '-llog', '-ldl', '-lm', '-pthread',
                '-Wl,--version-script,' + str(source / 'frida/_frida/extension.version'),
                '-o', str(extension)]
    print('[*] 编译原生扩展', flush=True)
    subprocess.run(command, check=True)
    # Verify ABI/loadability before allowing pip to install the extension.
    result = verify_extension(extension, version)
    if result.returncode != 0:
        output = (result.stdout or '') + (result.stderr or '')
        print(output, flush=True)
        if 'cannot locate symbol' in output and add_libpython_dependency(extension, libpython):
            print('[*] 已用 patchelf 补依赖，重新校验', flush=True)
            result = verify_extension(extension, version)
        if result.returncode != 0:
            raise SystemExit(SYMBOL_HINT + '\n' + (result.stdout or '') + (result.stderr or ''))
    print(result.stdout.strip(), flush=True)
    env = dict(os.environ, FRIDA_EXTENSION=str(extension))
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-build-isolation',
                    '--no-deps', '--force-reinstall', str(source)], env=env, check=True)
    result = subprocess.run([sys.executable, '-c', IMPORT_FRIDA], text=True, capture_output=True)
    if result.returncode != 0:
        output = (result.stdout or '') + (result.stderr or '')
        print(output, flush=True)
        installed = installed_extension()
        if 'cannot locate symbol' in output and installed and add_libpython_dependency(installed, libpython):
            print('[*] 已修补已安装的 _frida.abi3.so，重新导入', flush=True)
            result = subprocess.run([sys.executable, '-c', IMPORT_FRIDA], text=True, capture_output=True)
        if result.returncode != 0:
            raise SystemExit(SYMBOL_HINT + '\n' + (result.stdout or '') + (result.stderr or ''))
    print(result.stdout.strip(), flush=True)


if __name__ == '__main__':
    main()
