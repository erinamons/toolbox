# 工具箱 Toolbox

免费开源的 Windows 桌面工具集合——把网上那些「按次付费、强制注册、层层限制」的常用小工具，重新做成免费的本地版本。

## 为什么做这个

想转个 PDF 格式、解个 NCM 音乐文件，搜索引擎里一找：不是试用一次就要收费，就是限制文件大小、逼你注册、强塞水印。

这个项目的原则：

- **免费**：所有工具免费用，不限次数
- **本地处理**：文件不上传，全部在本地完成，隐私安全
- **无需注册**：下载即用，没有账号体系
- **开源**：代码全部公开，欢迎提交想法或直接加功能

## 内置工具

| 工具 | 说明 |
|------|------|
| PDF 转 JPG | 批量把 PDF 每页转成 JPG 图片，可选 DPI 与输出目录 |
| NCM 转 MP3 | 解密网易云音乐 NCM 格式为通用 MP3，保留元数据、封面，可选按「歌手 - 歌名」命名 |
| MediaInfo | 批量拖入视频/音频，查看完整技术参数（编码、分辨率、帧率、音轨、字幕、章节），可复制 MediaInfo 风格文本 |
| 视频压缩 | 本地视频压制：H.264/H.265 + CRF 质量滑条 + 速度预设 + 批量队列，完成后显示体积对比 |

> MediaInfo 与视频压缩依赖 `bin/ffprobe.exe`、`bin/ffmpeg.exe`（ffmpeg 官方 build 内含，安装包已自带）；从源码运行请把这两个 exe 放到仓库根目录 `bin/` 下，或加入系统 PATH。

## 下载

前往 [下载页](https://mochizuki.top/downloads.html) 获取最新版本安装包，每个版本都附带 SHA-256 校验值。

Windows 10 及以上系统可直接运行，无需安装依赖。

## 自动更新

应用内置更新检查：启动时自动对比服务器清单，发现新版本提示下载。你也可以在「关于」里手动检查。

## 从源码运行

依赖 Python 3.10+：

```bash
pip install PyQt5 requests pillow pycryptodome
python toolbox.py
```

## 打包

使用 PyInstaller 打包单文件 exe：

```bash
python build_exe.py
```

产物在 `dist/工具箱.exe`。

## 发布新版本

维护者使用（需要发布令牌）：

```bash
python release.py 1.2 "更新说明"
```

脚本会自动完成：打包 → 计算 SHA-256 → 建草稿 → 上传 → 发布 → 清单核验。

## 参与贡献

- **源码仓库**：https://github.com/erinamons/toolbox
- **提想法 / 报 Bug**：[下载页反馈区](https://mochizuki.top/downloads.html)提交，支持投票
- **加功能**：Fork 后在 `tools/` 目录新建工具模块（继承 `tools/base.py` 的 `ToolBase`），提 PR 即可

新工具开发只需三步：

1. 新建 `tools/your_tool.py`，继承 `ToolBase`，实现 UI 与逻辑
2. 在 `toolbox.py` 注册工具类
3. 准备一个 48x48 图标放 `assets/`

## License

[MIT](LICENSE)

本工具的 MediaInfo 功能使用了 FFmpeg 项目（`bin/ffprobe.exe`，LGPL/GPL），
其版权归 FFmpeg 项目及原作者所有，遵循各自许可证分发。
