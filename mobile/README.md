# 手机端 Hook（Termux + Frida）

用于已 root 的 Android **arm64 / x86_64** 设备。在指定的 QQ / 微信进程内，为 `com.lptiyu.tanke` 的 PackageInfo 返回指定证书。不会修改 APK、系统证书或账号数据；不保证第三方授权登录成功，可能触发风控。

## 手机安装与运行

将整个 `mobile` 目录放在 **Termux 私有 home 目录**内运行，不要直接从 `/sdcard` 运行可执行文件。

```bash
cd ~/budaolepao/mobile
bash install.sh
bash start.sh 1       # QQ :openSdk
bash start.sh 2       # 微信主进程
bash start.sh 1 --restart-server
```

依赖：Termux、root 授权、Python。默认客户端和 server 版本为 `16.7.19`。安装会按 Termux `uname -m` 选择 server、校验 ELF 架构/版本、安装 frida-python、生成 JS、启动 server 并验证 Frida 协议连接。

### Termux frida-python 原生构建

Termux 不一定有可用的官方 Android Python wheel。安装脚本先用 `--only-binary` 试官方 wheel，失败后保存 pip 日志，并用 `build_frida.py`：下载官方匹配版本的 Frida core devkit 和 PyPI 源码，用 Termux clang 只编译 Python C binding，再通过官方 setup.py 的 `FRIDA_EXTENSION` 入口安装。**不是完整的 core 源码构建，也不是普通 Linux wheel。**需要标准带 GIL 的 CPython；free-threaded Python 不支持。构建输出保存在 `bin/build-frida.log`。

**`_Py_NoneStruct` 符号错误**：Android 的 linker 不会把主程序符号暴露给 `dlopen` 的扩展模块，Termux 的 CPython 符号在 `libpython3.x.so` 里，只按桌面 Linux 的方式编译会得到 `dlopen failed: cannot locate symbol "_Py_NoneStruct"`。脚本现在链接扩展时显式带上 `-lpython3.x` / `-Wl,-rpath`，并在校验失败时用 `patchelf --add-needed` 兜底；需要 `pkg install patchelf`（安装脚本会自动装）。实在不行可临时绕过（把版本号换成 `ls $PREFIX/lib/libpython3*.so` 的结果）：

```bash
LD_PRELOAD=$PREFIX/lib/libpython3.14.so python -u hook.py --target qq
```



先运行客户端，再手动触发应用授权。QQ 默认等待精确进程名 `com.tencent.mobileqq:openSdk`；微信默认等待 `com.tencent.mm`。微信应在授权前通过系统设置强停后重开；划掉最近任务不等于强停。脚本不自动操作授权页，也不提交登录。

日志含义：

- `hook`：方法已安装。
- `ready`：Hook 安装阶段结束；同时检查前面有无 `err`，并留意 hook 数量。
- `patch`：目标 PackageInfo 已被改写，不代表服务端接受了授权。
- `已注入`：JS 已加载，不等于全部 Hook 安装成功。

`Ctrl-C` 会 detach 所有会话，server 保持运行。目标进程重启后客户端自动重新挂载，断线时清理旧会话并重连。轮询 attach 有启动竞争窗口，不能保证拦住进程最早期的签名查询；也不会追溯改写已缓存结果。

## 配置与调试

安装和后续运行保持相同配置：

```bash
FRIDA_VERSION=16.7.19 FRIDA_ADDR=127.0.0.1:27042 bash install.sh
```

- `FRIDA_VERSION`：client/server 版本。
- `FRIDA_ADDR`：监听和连接地址；建议仅监听回环，勿暴露给局域网。
- `FRIDA_SERVER_URL`：自定义 server 下载地址，仍做架构、版本校验。
- `FRIDA_LOCAL`：root 部署路径，默认 `/data/local/tmp/frida-server`。
- `FRIDA_LOG`：server 日志，默认 `/data/local/tmp/frida-server.log`。

客户端参数示例：

```bash
python hook.py --target qq
python hook.py --target wechat --duration 30
python hook.py --proc com.tencent.mobileqq:openSdk --interval 0.25
python hook.py --output hook/signature-spoof.js
```

`--proc` 可重复并覆盖默认进程列表；`--duration` 是有限正秒数；`--output` 生成可手动注入的独立 JS，无需 frida-python。启动失败时先查 server 日志、root、架构/版本、端口和系统策略。脚本不会自动关闭 SELinux。

## 实现文件

| 文件 | 用途 |
|---|---|
| [install.sh](install.sh) | 依赖、下载、版本/架构检查、客户端安装 |
| [build_frida.py](build_frida.py) | 官方 devkit 配对构建 Android binding |
| [start.sh](start.sh) | 目标选择、server 检查、启动客户端 |
| [common.sh](common.sh) | 配置、root、server 启停、连接检查 |
| [hook.py](hook.py) | 证书内联、进程轮询、attach/detach 和重连 |
| [spoof.template.js](hook/spoof.template.js) | 仅针对目标包的 Hook |
| [official_cert.der](official_cert.der) | 签名替换所用证书 |
| [test_hook.py](test_hook.py) | 离线回归测试 |
| [verify_device.py](verify_device.py) | 设备内签名替换/范围隔离测试 |

Hook 覆盖 `getPackageInfo` 的 String 包名重载、三参数 `getPackageInfoAsUser`、`getInstalledPackages` 的 int/新 flags 重载。`SigningInfo` 使用 WeakHashMap 标记目标包返回对象；未标记对象仍调用原方法。不会处理注入前缓存、原生层读 APK 证书、服务端校验或未覆盖链路，不是通用校验绕过。


