#!/usr/bin/env python3
"""Build the official Python extension against the matching Android core devkit."""
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import sysconfig
import tarfile
import urllib.request


def download(url, destination):
    print('[*] 下载 ' + url, flush=True)
    temporary = destination.with_suffix(destination.suffix + '.part')
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
        import shutil
        shutil.copyfileobj(response, output)
    temporary.replace(destination)


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
    command += ['-lfrida-core', '-llog', '-ldl', '-lm', '-pthread',
                '-Wl,--version-script,' + str(source / 'frida/_frida/extension.version'),
                '-o', str(extension)]
    print('[*] 编译原生扩展', flush=True)
    subprocess.run(command, check=True)
    # Verify ABI/loadability before allowing pip to install the extension.
    subprocess.run([sys.executable, '-c',
                    'import importlib.util,sys; s=importlib.util.spec_from_file_location("_frida",sys.argv[1]); '
                    'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
                    'assert m.__version__ == sys.argv[2]; print("NATIVE_EXTENSION_OK",m.__version__)',
                    str(extension), version], check=True)
    env = dict(os.environ, FRIDA_EXTENSION=str(extension))
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-build-isolation',
                    '--no-deps', str(source)], env=env, check=True)
    subprocess.run([sys.executable, '-c', 'import frida; print("FRIDA_PYTHON_OK",frida.__version__)'], check=True)


if __name__ == '__main__':
    main()
