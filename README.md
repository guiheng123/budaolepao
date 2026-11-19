# 步道乐跑  脱壳重打包

把步道乐跑4.3.3还原成一份可以正常安装、正常启动的明文APK。

实测环境：MuMu Player（Android 15 / SDK 35，x86_64 + ARM64 houdini 转译），重打包后启动进入 `MainActivity`，

底部五个 Tab —— 动态 / 校园 / 乐跑 / 活动 / 我的 —— 全部可切换，进程稳定存活。

| 项目 | 值 |
|---|---|
| 包名 | `com.lptiyu.tanke` |
| 版本 | 4.3.3（versionCode 233） |
| 原包大小 | 133,044,116 B（约 127 MiB） |
| 重打包后 | 131,524,236 B（约 125 MiB） |
| SHA-256（成品） | `5F8F55A5FB8B58B3A52A9D446C691FA0867E79796BDE84AF610C3FE0CA541DE0` |
| 签名 | debug key，zipalign + v1/v2/v3 |

---

## 为什么会有这个项目

**实测乐跑4.3.3在WSA MUMU等虚拟机中无法正常启动**

启动即死：

```
F DEBUG : signal 0 (SIGSEGV), code 1 (SEGV_MAPERR), Cause: null pointer dereference
  #00 pc ... /system/lib64/arm64/libdexfile.so
        art::DexFileLoader::OpenFromZipEntry(...)+76
  #01 pc ... base.apk!/lib/arm64-v8a/libkadp.so
```

壳的 `libkadp.so` 直接调用了 ART 的私有符号 `DexFileLoader::OpenFromZipEntry`，而 Android 15 的 ART 里这个 ABI 已经变了，
于是连壳自己都跑不起来 —— 加固包既不能用，也没法在它身上做动态脱壳。

因此解决方案就是：**自己把业务 dex 拿出来、把壳剥掉、把校验拆掉，重打一个包**。

## 能做什么

- 在 x86_64 模拟器（带 ARM 转译）上安装并启动，不再需要 ARM 真机
- 跳过签名 SHA-1 校验，不再弹「请前往官方渠道下载正版app」
- 壳 so / VData 全部剥离，进程不再被壳接管
- 不再加载 `KwProtectSDK` / `kwsdataenc`，模拟器检测与自杀逻辑失效（`UniverseSecNo2: [hit] No3` → `SIGKILL`）

## 安装

从release下载apk文件

安装前卸载原版，官方签名与 debug key 不同，覆盖安装一定失败，必须先卸载

视频教程：https://www.bilibili.com/video/BV1crsD6yE7N/

## TIP 

若使用**QQ登录**，会提示该应用非官方正版应用，修复教程请查看 [QQ登录说明](./QQ登录说明.md)

**微信**，会提示签名不对，修复教程请查看 [微信登录说明](./微信登录说明.md)

感谢您的star和issues

*此项目仅供学习使用*
