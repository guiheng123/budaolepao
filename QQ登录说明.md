# QQ 登录绕过

重打包包是 debug 签名，QQ 授权页会弹「该应用非官方正版应用，请去相应…」。
本目录的工具在 QQ 侧伪造签名，绕过该校验。

## 一、使用方法

### 0. 环境要求

| 项 | 要求 |
|---|---|
| 设备 | MuMu Player 12（已开 root）；`adb devices` 里能看到一台 `device` 状态的设备 |
| 已装应用 | `com.lptiyu.tanke`（重打包 debug 签名包），QQ 已登录 |
| 本机 | Python 3 + `frida`（版本与 frida-server 对齐：16.7.19）、adb |
| 目录 | 本目录的 `tools/frida/frida-server` 是 **x86_64** 版，对应 MuMu 的 x86_64 镜像 |

### 1. 装依赖（可忽略）

```powershell
pip install -r requirements.txt
```

### 2. 如何使用

二选一

**一键启动 hook**

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_hook.ps1
```
在终端输入 1

脚本依次做三件事：`adb connect/root/forward tcp:27042` → 推送并启动 frida-server → 常驻运行
`tools\wait_opensdk.py`。**窗口保持开着**，Ctrl-C 结束。

### 3. 登录

打开步道乐跑 → 「点击登录」→「QQ登录」→ 授权页直接点「同意」

脚本输出应为：

```
连上 frida 127.0.0.1:27042，等待 com.tencent.mobileqq:openSdk 出现 ...
>>> 已挂 hook: com.tencent.mobileqq:openSdk (pid 9255)
[openSdk] {'t': 'ready'}
[openSdk] {'t': 'hook', 'what': 'getPackageInfo(int)'}
[openSdk] {'t': 'hook', 'what': 'SigningInfo'}
[openSdk] {'t': 'hook', 'what': 'getInstalledPackages'}
[openSdk] {'t': 'patch', 'where': 'getPackageInfo(int)'}
```

看到 `patch` 就说明签名已被替换，此时点「同意」即可通过。

### 4. 之后

登录成功后 app 侧 token 已下发，**只要不退出登录就不必再开脚本**；重启模拟器或重启 QQ 后需重跑第 2 步

### 5. 可选方案

自行安装有关应用签名伪装的lsp模块，规则：

```
作用域: com.tencent.mobileqq
包名:   com.lptiyu.tanke
签名:   tools/official_cert.der
```

## 二、工作原理

1. QQ 互联的 SDK 把签名校验放在 **QQ 客户端**里，不在 app 里：app 只是调起 QQ 的授权页
   （`com.tencent.open.agent...`，跑在 `com.tencent.mobileqq:openSdk` 进程）。
2. 授权页用调用方包名 `com.lptiyu.tanke` 调 `PackageManager.getPackageInfo(pkg, GET_SIGNATURES|GET_SIGNING_CERTIFICATES)`，
   把证书 MD5 与开放平台登记值比对，不一致就弹「非官方正版应用」。

   | 签名 | 证书 MD5 |
   |---|---|
   | 官方（Qudong 证书，SHA1 `CA:17:12:94:…:20:48`） | `D6AB92F37E0BDBFF74D08A64C19EA1D8` |
   | 重签（Android Debug，SHA1 `5D:08:26:4B:…`） | 不一致 |

3. 改 apk 里的代码对这条链路无效（校验在 QQ 进程内，且它读的是安装后的实际签名）。
   因此用 frida 在 **`:openSdk` 进程**里 hook `PackageManager.getPackageInfo` / `getInstalledPackages` /
   `SigningInfo.getApkContentsSigners`，把查询 `com.lptiyu.tanke` 得到的 `PackageInfo.signatures`
   替换成 `official_cert.der`（官方证书）。QQ 拿到的就是"官方签名"，比对通过。
4. 只改返回值，不动 QQ 本体，进程一退即失效，所以要脚本常驻；hook QQ 主进程无效，授权页只在 `:openSdk` 里。

## 三、文件说明

| 路径 | 作用 |
|---|---|
| `tools\start_hook.ps1` | 一键：adb root / 起 frida-server / 挂 hook |
| `tools\wait_opensdk.py` | 常驻轮询 `:openSdk`，出现即 attach 并注入签名伪造脚本 |
| `tools\official_cert.der` | 从官方包 v2 签名块提取的证书（867 B，MD5 `D6AB92F37E0BDBFF74D08A64C19EA1D8`） |
| `tools\frida\frida-server` | frida-server 16.7.19，x86_64 |

## 四、已知限制

- QQ 换版本可能改变校验实现
- **账号可能触发风控**
