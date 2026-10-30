# macOS arm64 自包含开发包

构建工具需要宿主 Python 3.14（读取 `.tar.zst` 的标准库支持）、uv 和可选系统 codesign；App 内运行 Python 3.13.18，不依赖构建工具。没有下载器、全局环境安装、账号迁移或 SDK 安装。输出必须是不存在的 `.app`，禁止覆盖。

## 固定一手输入

- Electron 43.3.0 `electron-v43.3.0-darwin-arm64.zip`，SHA256 `ee939d1564d83d61032b3b3cb23af4e46005a4900c91f0695f7ed793f0ce6e83`，来源：[官方发行](https://github.com/electron/electron/releases/tag/v43.3.0) / `SHASUMS256.txt`。保留框架内部相对 symlink、可执行位和 Electron/Chromium 许可证。
- Astral [python-build-standalone 20261026](https://github.com/astral-sh/python-build-standalone/releases/tag/20261026)：`cpython-3.13.18+20261026-aarch64-apple-darwin-install_only.tar.gz`，SHA256 `e5af2fde6a937a0e0c795a0c595c4efb70578d57463a2657c819992b9b9acbac`。
- 同发行 `cpython-3.13.18+20261026-aarch64-apple-darwin-pgo+lto-full.tar.zst`，SHA256 `5706f1fdf82f7ea10b56a9b9cbadfa5f372010568a9794f19e0af4c48d975f34`。官方 API 的 asset digest 与固定 SHA 比对；没有声称验证发布者签名或 Sigstore。精简运行时不含完整第三方 notices，因此从 full 提取 metadata 与所有引用的许可证，并核对两个归档中的解释器字节相同。参见[官方运行/许可说明](https://github.com/astral-sh/python-build-standalone/blob/20261026/docs/running.rst)。
- `python-runtime-provenance.json` 为人工下载后保存的官方 release metadata：`source` 为上述 release URL，`asset` 和 `full_asset` 为官方 assets 对象（含 name、digest、browser_download_url）。不能用任意新哈希绕过脚本内 pin。
- 依赖由当前 `requirements.txt`、Python 3.13 / `aarch64-apple-darwin` 解析成带 SHA256 的锁，并下载 arm64/universal2/any wheels。跨端共享的 requirements 变化时重新解析锁，不能借用 Windows wheelhouse。不要读取或携带已有 venv、DB、密钥、认证配置。

## 离线构建

准备依赖时使用公开索引、隔离构建配置；这一步需要网络，正式构建无网络：

```sh
uv pip compile requirements.txt --python-version 3.13 --python-platform aarch64-apple-darwin \
  --only-binary :all: --generate-hashes --default-index https://pypi.org/simple \
  --no-config --no-python-downloads -o /cache/requirements-macos-arm64.lock
python3 -m pip --isolated --disable-pip-version-check download --platform macosx_11_0_arm64 \
  --python-version 313 --implementation cp --abi cp313 --only-binary :all: --require-hashes \
  --index-url https://pypi.org/simple --dest /cache/wheelhouse -r /cache/requirements-macos-arm64.lock
```

以下全部是本地输入；先加 `--preflight` 校验后去掉该选项执行。缓存路径按实际位置填写；程序不替用户执行下载：

```sh
python3 desktop/package-macos.py --project-root /path/to/source \
  --electron-zip /cache/electron-v43.3.0-darwin-arm64.zip \
  --python-tar /cache/cpython-3.13.18+20261026-aarch64-apple-darwin-install_only.tar.gz \
  --python-full-tar /cache/cpython-3.13.18+20261026-aarch64-apple-darwin-pgo+lto-full.tar.zst \
  --python-provenance /cache/python-runtime-provenance.json \
  --requirements-lock /cache/requirements-macos-arm64.lock --wheels-dir /cache/wheelhouse \
  --output /new/path/回响.app --profile cn.xinji.echo.portable --adhoc-sign
```

`Contents/Resources` 内含 SOURCE-MANIFEST / BUILD-MANIFEST / DEPENDENCIES / Python provenance。源码清单不含官方运行时；运行时记录输入 archive SHA，ad-hoc 签名会修改代码签名。新数据写入所选用户 profile，包体保持不变。不同 profile 不能共享占用的后端端口；不自动结束未知进程或更换端口。

## 发布验收仍分层

1. 校验全部复制源、运行时、wheel 哈希和许可证；扫描无私人 DB/配置/密钥。
2. 移动整个 App 到含空格/中文的新目录，用包内 Python、全新临时数据运行真实后端，核验 HTTP、仅回环监听、PID/cwd 归属、退出与重新启动；比对运行前后包体内容。
3. 在解锁的真实 Mac 中启动 GUI，验收聊天/输入/文件/菜单/托盘/通知与权限。没有 Developer ID、公证、自动更新或跨机器验收承诺；系统拦截时保留原提示，不关闭防护。

当前真实运行和 GUI 结论应写入本轮外部验收报告；源码和静态测试本身不表示 GUI 已通过。可用的模型仍需用户在新 profile 显式配置，CLI/日历/硬件仍是独立连接验收。


R13额外纳入可手动运行的设备服务runner和包内依赖bootstrap；不拷贝其他scripts或TLS证书/私钥，默认不启用远程入口。用法见desktop/README，最终组装报告另验包内解释器执行该辅助入口。R13 CFBundleVersion=13；这不是Developer ID签名。

## R15 连接资源

`package-macos.py` 的 CFBundleVersion 为 15。离线预检要求连接 selector、受限 shared preload、身份探测和权限门控 7 个普通文件齐全；依既有 JS/HTML/CSS 白名单复制，不增加依赖。`desktop-connection.json` 与 `desktop-preferences.json` 一律排除，便携 profile 首用仍未配模型。旧开发指针方式同步包含连接界面。GUI／真实共享连接须另验，组装或回环 HTTP 不代替点击验证。
