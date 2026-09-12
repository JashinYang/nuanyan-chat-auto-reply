# Windows 发行组件对照表

本表以 Python 3.12 独立公开构建环境、已安装 wheel 的 `METADATA`/`LICENSE`/`NOTICE` 和 PyInstaller 实际收集结果为依据。`进入 EXE/ZIP` 中“是”表示代码、数据、运行时或构建引导组件进入发布目录；“构建”表示仅构建工具的 bootloader/运行时钩子进入成品。

| 组件 | 版本 | 直接/传递 | 许可证 | 上游 | 进入 EXE/ZIP |
|---|---:|---|---|---|---|
| Requests | 2.34.2 | 直接 | Apache-2.0 + NOTICE | https://github.com/psf/requests | 是 |
| urllib3 | 2.7.0 | 传递 | MIT | https://github.com/urllib3/urllib3 | 是 |
| certifi | 2026.7.22 | 传递 | MPL-2.0 | https://github.com/certifi/python-certifi | 是 |
| charset-normalizer | 3.5.1 | 传递 | MIT | https://github.com/jawah/charset_normalizer | 是 |
| idna | 3.19 | 传递 | BSD-3-Clause | https://github.com/kjd/idna | 是 |
| UIAutomation | 2.0.29 | 直接 | Apache-2.0 | https://github.com/yinkaisheng/Python-UIAutomation-for-Windows | 是（含 x86/x64 客户端 DLL） |
| comtypes | 1.4.16 | 传递 | MIT | https://github.com/enthought/comtypes | 是 |
| pywin32 | 311 | 直接 | PSF-2.0 | https://github.com/mhammond/pywin32 | 是 |
| pywebview | 6.1 | 直接 | BSD-3-Clause | https://github.com/r0x0r/pywebview | 是 |
| pythonnet | 3.1.0 | 传递 | MIT | https://github.com/pythonnet/pythonnet | 是 |
| clr-loader | 0.3.1 | 传递 | MIT | https://github.com/pythonnet/clr-loader | 是 |
| cffi | 2.1.1 | 传递 | MIT-0 | https://github.com/python-cffi/cffi | 是 |
| pycparser | 3.0 | 传递 | BSD-3-Clause | https://github.com/eliben/pycparser | 是 |
| proxy-tools | 0.1.0 | 传递 | MIT | https://github.com/jtushman/proxy_tools | 是 |
| bottle | 0.13.4 | 传递 | MIT | https://github.com/bottlepy/bottle | 是 |
| typing-extensions | 4.16.0 | 传递 | PSF-2.0 | https://github.com/python/typing_extensions | 是 |
| windows-capture | 2.0.1 | 直接 | MIT | https://github.com/NiiightmareXD/windows-capture | 是 |
| NumPy | 2.5.3 | 直接/传递 | BSD-3-Clause 及随附第三方许可 | https://github.com/numpy/numpy | 是（含 OpenBLAS 等） |
| opencv-python / OpenCV | 5.0.0.93 | 传递 | wheel 脚本 MIT；OpenCV Apache-2.0；随附 FFmpeg LGPL-2.1 等 | https://github.com/opencv/opencv-python | 是 |
| setuptools | 84.0.0 | PyInstaller 运行时钩子引入 | MIT | https://github.com/pypa/setuptools | 是（含其 vendored 子组件） |
| packaging | 26.3 | PyInstaller 运行时钩子引入 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging | 是 |
| pywin32-ctypes | 0.2.3 | PyInstaller 运行时钩子引入 | BSD-3-Clause | https://github.com/enthought/pywin32-ctypes | 是 |
| Microsoft WebView2 SDK assemblies | 1.0.2957.106 | pywebview 内含 | Microsoft 软件许可条款 | https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.2957.106 | 是；WebView2 Runtime 本体否 |
| Python runtime | 3.12.x | 运行时 | PSF-2.0 及随附第三方许可 | https://www.python.org/ | 是 |
| PyInstaller | 6.22.2 | 构建 | GPL-2.0-or-later WITH Bootloader-exception；运行时钩子 Apache-2.0 | https://pyinstaller.org/en/stable/license.html | 构建（bootloader/钩子） |
| QQSafeChat 改编部分 | 2026 年取得版本 | 源码归属 | MIT | https://github.com/TheD0ubleC/QQSafeChat | 是（改编源码） |

`opencv-python` 的完整 `LICENSE-3RD-PARTY.txt` 和 NumPy wheel 的完整 `licenses/` 子树随包分发，因此其中的 OpenBLAS、LAPACK、SIMD、FFmpeg 等嵌入组件不在本表逐行重复。构建后由 `tools/license_audit.py` 核对版本、许可文件和禁止扩展名；`tools/secret_scan.py` 扫描工作树与 Git 历史。
