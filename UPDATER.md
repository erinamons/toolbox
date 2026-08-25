# 工具箱自动更新说明

## 组成

| 文件 | 作用 |
|------|------|
| `updater.py` | 更新核心模块（纯标准库，无 Qt 依赖，可单独测试） |
| `toolbox.py` | 主程序，已集成更新 UI（菜单/弹窗/进度条） |
| `test_updater.py` | 单元测试：34 项（版本比较/清单/下载校验/跳过版本） |
| `test_e2e_selfupdate.py` | E2E：真实打包两个版本，验证完整自替换重启链路 |
| `e2e_core.py` / `e2e_old_app.py` / `e2e_new_app.py` | E2E 用的最小应用壳 |
| `make_update_manifest.py` | 发布脚本：算哈希、生成 update.json 与上传文件 |
| `release/` | 发布产物输出目录 |

## 清单协议（update.json）

```json
{
  "latest": "1.2",
  "url": "https://mochizuki.top/downloads/toolbox-latest.exe",
  "sha256": "<64 位小写十六进制>",
  "size": 66158360,
  "notes": "更新说明",
  "mandatory": false
}
```

- `latest` 版本比较用整数元组（1.10 > 1.9 正确；1.2 == 1.2.0）
- `sha256` + `size` 双重校验，防下载损坏与供应链投毒
- `mandatory: true` 时更新弹窗只留"立即更新"

## 发版流程

```
1. 改 toolbox.py 里的 APP_VERSION（如 "1.2"）
2. python build_exe.py                        # 打新包
3. python make_update_manifest.py 1.2 "说明"  # 生成 release/
4. 把 release/toolbox-latest.exe 和 release/update.json 上传到
   https://mochizuki.top/downloads/ 目录
5. 用户端：启动工具箱 1.5 秒后自动静默检查 → 弹窗 → 下载 → 安装重启
```

## 自替换原理（PyInstaller onefile 便携 exe）

```
运行中的旧 exe
  ├─ 下载新版到 %TEMP%\toolbox_update_*.exe（分块+流式 SHA-256）
  ├─ 校验通过 → rename 自己为 工具箱.exe.old   （Windows 允许 rename 运行中的 exe）
  ├─ 新 exe move 到原路径（失败自动回滚）
  ├─ 剥离 _PYI_* 环境变量后 Popen 新 exe
  ├─ 延迟 1.5s 退出（给新版 bootloader 父进程校验留窗口）
  └─ os._exit(0)
新版启动
  └─ main() 首行 cleanup_old_files() 删除 .old 残留
```

## 两个关键工程细节（踩坑记录）

1. **PyInstaller 6.14+ 父进程安全校验**：onefile 子进程 bootloader
   依据 `_PYI_PARENT_PROCESS_LEVEL` 环境变量校验父进程链。旧 exe
   的 Python 进程直接 Popen 新 exe 时会继承这些变量，导致新 exe
   报 `Security validation failure: parent process has different
   executable` 拒绝启动。**修复**：Popen 时构造剥离 `_PYI_*` /
   `_MEIPASS2` / `_MEIPASS` 的干净环境。

2. **父进程存活窗口**：即使环境剥离，旧进程 `os._exit(0)` 过快
   退出仍会触发 `failed to obtain executable path for parent
   process`（校验瞬间父进程已死）。**修复**：Popen 新版后延迟
   1.5 秒再退出。

## 测试

```
python test_updater.py            # 单元测试 → UPDATER_TESTS_OK
python test_e2e_selfupdate.py     # 端到端 → E2E_SELF_UPDATE_OK（需几分钟打包）
```

E2E 覆盖：清单拉取 → 下载校验 → rename .old → 自替换 → 新版重启
（标记文件 APP_V=1.0）→ 原路径字节级等于新版 → .old 清理。

## 状态持久化

`%LOCALAPPDATA%\工具箱\updater\state.json` 存"跳过此版"记录；
清单版本高于跳过版本时恢复提示（跳过 1.2 后发布 1.3 会重新弹窗）。
