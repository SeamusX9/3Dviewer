# 3D 模型预览

基于 **PySide6 + PyVista** 的桌面端 3D 模型浏览器，支持拖放打开、多视角查看与快照导出。

## 功能

- 打开 / 拖放加载常见 3D 格式
- 左键旋转、右键平移、滚轮缩放
- 轴向视角（X / Y / Z，再点一次切换正负方向）
- 显示边线、重置视角
- 导出 PNG / JPEG 快照
- 状态栏显示顶点数与三角面数

## 支持格式

| 格式 | 扩展名 |
|------|--------|
| glTF / GLB | `.glb` `.gltf` |
| Autodesk FBX | `.fbx` |
| Wavefront OBJ | `.obj` |
| STL | `.stl` |
| 3D Studio | `.3ds` `.3d` |
| SketchUp | `.skp` |

## 环境要求

- Windows（当前主要开发和打包目标）
- Python **3.12+**

## 安装与运行

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

任选一种方式启动：

```bat
run.bat
```

或：

```bat
.venv\Scripts\python.exe main.py
```

也可把模型路径作为参数传入：

```bat
.venv\Scripts\python.exe main.py path\to\model.glb
```

## 操作说明

| 操作 | 说明 |
|------|------|
| 打开文件 | 通过对话框选择模型 |
| 拖放 | 将支持的模型拖入窗口 |
| 快照 | 将当前画面保存为图片 |
| 重置视角 | 回到默认相机位置 |
| X / Y / Z | 切换到对应轴向视角；再次点击切换反向 |
| 显示边线 | 叠加网格边线 |

## 项目结构

```
3Dviewer/
├── main.py            # 主窗口与交互
├── loader.py          # 模型加载（assimp / trimesh / openskp）
├── make_icon.py       # 生成应用图标
├── icon.ico           # 应用图标
├── preview.spec       # PyInstaller 打包配置
├── requirements.txt   # 依赖
└── run.bat            # Windows 启动脚本
```

## 打包为可执行文件

需先安装 [PyInstaller](https://pyinstaller.org/)：

```bat
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller preview.spec
```

产物位于 `dist/3D模型预览/`。

## 依赖概览

见 [`requirements.txt`](requirements.txt)：

- `PySide6` — GUI
- `pyvista` / `pyvistaqt` — 3D 渲染
- `assimp-py` — FBX / OBJ / STL / 3DS 等
- `openskp` — SketchUp（`.skp`）
- `numpy` — 网格数据

## 许可证

如无需要，可自行补充开源许可证。
