"""Desktop preview for GLB, FBX, OBJ, STL, 3DS/3D and SKP models."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_API", "PySide6")

if getattr(sys, "frozen", False):
    _bundle = getattr(sys, "_MEIPASS", "")
    if _bundle and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(_bundle)
    os.environ["PATH"] = _bundle + os.pathsep + os.environ.get("PATH", "")

    def _frozen_excepthook(exc_type, exc, tb):
        import traceback
        log = Path(sys.executable).resolve().parent / "error.log"
        try:
            log.write_text("".join(traceback.format_exception(exc_type, exc, tb)), encoding="utf-8")
        except Exception:
            pass

    sys.excepthook = _frozen_excepthook

import numpy as np
import pyvista as pv
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QIcon, QImage
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QGridLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from pyvistaqt import QtInteractor
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera

from loader import FILE_FILTER, LoadedModel, MeshPart, ModelLoadError, is_supported, load_model

pv.global_theme.smooth_shading = True
pv.global_theme.multi_samples = 8


class InspectStyle(vtkInteractorStyleTrackballCamera):
    """Left button orbits, right button pans, wheel zooms."""

    def OnRightButtonDown(self):  # noqa: N802
        vtkInteractorStyleTrackballCamera.OnMiddleButtonDown(self)

    def OnRightButtonUp(self):  # noqa: N802
        vtkInteractorStyleTrackballCamera.OnMiddleButtonUp(self)

    def OnMiddleButtonDown(self):  # noqa: N802
        vtkInteractorStyleTrackballCamera.OnRightButtonDown(self)

    def OnMiddleButtonUp(self):  # noqa: N802
        vtkInteractorStyleTrackballCamera.OnRightButtonUp(self)


class ModelView(QtInteractor):
    file_dropped = Signal(str)

    def dragEnterEvent(self, event):  # noqa: N802
        if _dropped_model(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if _dropped_model(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802
        path = _dropped_model(event)
        if path is None:
            event.ignore()
            return
        self.file_dropped.emit(path)
        event.acceptProposedAction()


class DropHint(QWidget):
    def __init__(self, on_drop):
        super().__init__()
        self._on_drop = on_drop
        self.setObjectName("dropHint")
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(72, 72, 72, 72)
        card = QLabel(
            "将模型拖放到窗口中\n\n"
            "GLB    FBX    OBJ    STL    3DS / 3D    SKP\n\n"
            "也可以点击「打开文件」"
        )
        card.setObjectName("dropCard")
        card.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(card)

    def dragEnterEvent(self, event):  # noqa: N802
        if _dropped_model(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if _dropped_model(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802
        path = _dropped_model(event)
        if path is None:
            event.ignore()
            return
        self._on_drop(path)
        event.acceptProposedAction()


class LoadThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            self.succeeded.emit(load_model(self.path))
        except ModelLoadError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"无法读取该模型：{exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D 模型预览")
        self.setWindowIcon(_app_icon())
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self._model: LoadedModel | None = None
        self._worker: LoadThread | None = None
        self._pending: str | None = None
        self._style: InspectStyle | None = None
        self._cursor_pushed = False
        self._last_dir = str(Path.home())
        self._axis: str | None = None
        self._axis_flip = False
        self.view_buttons: dict[str, QPushButton] = {}

        self._build_ui()
        self._apply_camera_style()
        self._show_empty()

    def _build_ui(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self.addToolBar(toolbar)

        title = QLabel("3D 模型预览")
        title.setObjectName("appTitle")
        toolbar.addWidget(title)
        toolbar.addSeparator()

        self.open_button = QPushButton("打开文件")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.choose_file)
        toolbar.addWidget(self.open_button)

        self.snapshot_button = QPushButton("快照")
        self.snapshot_button.clicked.connect(self.save_snapshot)
        toolbar.addWidget(self.snapshot_button)

        self.reset_button = QPushButton("重置视角")
        self.reset_button.clicked.connect(self.reset_view)
        toolbar.addWidget(self.reset_button)

        toolbar.addSeparator()
        view_label = QLabel("视角")
        view_label.setObjectName("viewLabel")
        toolbar.addWidget(view_label)
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        for axis, tip in (
            ("x", "从 +X 方向看模型。再点一次切到 -X。"),
            ("y", "从 +Y 方向看模型。再点一次切到 -Y。"),
            ("z", "从 +Z 方向看模型。再点一次切到 -Z。"),
        ):
            button = QPushButton(axis.upper())
            button.setObjectName("axisView")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.clicked.connect(lambda _checked=False, axis=axis: self.set_axis_view(axis))
            self._view_group.addButton(button)
            toolbar.addWidget(button)
            self.view_buttons[axis] = button

        self.edges_button = QPushButton("显示边线")
        self.edges_button.setCheckable(True)
        self.edges_button.toggled.connect(self._on_edges_toggled)
        toolbar.addWidget(self.edges_button)

        spacer = QWidget()
        spacer.setObjectName("spacer")
        toolbar.addWidget(spacer)

        central = QWidget()
        central.setObjectName("central")
        grid = QGridLayout(central)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        self.view = ModelView(central, multi_samples=8)
        self.view.file_dropped.connect(self.open_path)
        self.view.setAcceptDrops(True)
        grid.addWidget(self.view, 0, 0)

        self.hint = DropHint(self.open_path)
        grid.addWidget(self.hint, 0, 0)

        self.setCentralWidget(central)

        status = QStatusBar()
        self.setStatusBar(status)
        self.file_label = QLabel("未打开文件")
        self.stats_label = QLabel("")
        self.help_label = QLabel("左键旋转    右键平移    滚轮缩放")
        status.addWidget(self.file_label, 1)
        status.addWidget(self.stats_label)
        status.addPermanentWidget(self.help_label)
        self._set_busy(False)

    def choose_file(self):
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择模型",
            self._last_dir,
            FILE_FILTER,
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str):
        source = str(Path(path))
        if not is_supported(source):
            QMessageBox.warning(
                self,
                "无法预览",
                f"不支持的格式：{Path(source).suffix or '无扩展名'}\n"
                "支持 GLB、GLTF、FBX、OBJ、STL、3DS、3D、SKP。",
            )
            return
        if self._worker is not None and self._worker.isRunning():
            self._pending = source
            self.file_label.setText(f"等待加载  {Path(source).name}")
            return
        self._start_load(source)

    def save_snapshot(self):
        if self._model is None:
            QMessageBox.information(self, "快照", "请先打开一个模型。")
            return

        source = Path(self._model.path)
        default = str(source.with_name(f"{source.stem}_snapshot.png"))
        path, selected = QFileDialog.getSaveFileName(
            self,
            "保存快照",
            default,
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if not path:
            return

        path = _with_image_suffix(path, selected)
        try:
            self.view.render()
            image = self.view.screenshot(transparent_background=False, return_img=True)
            _save_image(path, image)
        except Exception as exc:
            QMessageBox.critical(self, "快照失败", f"无法保存图片：\n{exc}")
            return
        self.statusBar().showMessage(f"已保存快照：{path}", 8000)

    def reset_view(self):
        if self._model is None:
            return
        self._frame_model()

    def set_axis_view(self, axis: str):
        if self._model is None:
            return
        if self._axis == axis:
            self._axis_flip = not self._axis_flip
        else:
            self._axis = axis
            self._axis_flip = False
        self._mark_axis_button()
        self._apply_axis_view()
        side = "-" if self._axis_flip else "+"
        self.statusBar().showMessage(f"当前视角：{side}{axis.upper()}。再点一次可切换到另一侧。", 5000)

    def dragEnterEvent(self, self_event):  # noqa: N802
        if _dropped_model(self_event) is not None:
            self_event.acceptProposedAction()
        else:
            self_event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if _dropped_model(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802
        path = _dropped_model(event)
        if path is None:
            event.ignore()
            return
        self.open_path(path)
        event.acceptProposedAction()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._apply_camera_style()

    def closeEvent(self, event):  # noqa: N802
        worker = self._worker
        if worker is not None:
            for signal, slot in (
                (worker.succeeded, self._on_loaded),
                (worker.failed, self._on_failed),
                (worker.finished, self._on_worker_finished),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            if worker.isRunning():
                worker.wait(1500)
        self.view.close()
        super().closeEvent(event)

    def _start_load(self, path: str):
        self._last_dir = str(Path(path).parent)
        self._set_busy(True)
        self.file_label.setText(f"正在加载  {Path(path).name}")
        self.stats_label.setText("")
        worker = LoadThread(path)
        worker.succeeded.connect(self._on_loaded)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _on_loaded(self, model: LoadedModel):
        self._model = model
        try:
            self._display(model)
        except Exception as exc:
            self._model = None
            self._show_empty()
            QMessageBox.critical(self, "无法预览", f"模型已读出，但无法显示：\n{exc}")
            return
        name = Path(model.path).name
        self.file_label.setText(name)
        self.stats_label.setText(f"顶点 {model.vertex_count:,}    三角面 {model.face_count:,}")
        self.statusBar().showMessage(f"已打开 {model.path}", 5000)

    def _on_failed(self, message: str):
        self._model = None
        self._show_empty()
        self.file_label.setText("未打开文件")
        self.stats_label.setText("")
        QMessageBox.warning(self, "无法预览", message)

    def _on_worker_finished(self):
        self._set_busy(False)
        pending = self._pending
        self._pending = None
        if pending:
            self._start_load(pending)

    def _on_edges_toggled(self, _checked: bool):
        if self._model is not None:
            self._display(self._model)

    def _display(self, model: LoadedModel):
        self.hint.hide()
        self.view.clear()
        self.view.set_background("#12151c", top="#2c384c")
        try:
            self.view.enable_lightkit()
        except Exception:
            pass

        show_edges = self.edges_button.isChecked()
        for part in model.parts:
            mesh = _polydata(part)
            kwargs = {
                "smooth_shading": True,
                "specular": 0.28,
                "specular_power": 18,
                "ambient": 0.2,
                "diffuse": 0.85,
                "show_edges": show_edges,
                "edge_color": "#1c212b",
                "line_width": 1,
            }
            if part.vertex_colors is not None:
                mesh.point_data["RGB"] = part.vertex_colors
                kwargs["scalars"] = "RGB"
                kwargs["rgb"] = True
            elif part.color is not None:
                kwargs["color"] = part.color
            else:
                kwargs["color"] = "#d5dbe3"
            self.view.add_mesh(mesh, **kwargs)

        try:
            self.view.add_axes(line_width=2)
        except Exception:
            pass
        self._frame_model()
        self._apply_camera_style()

    def _show_empty(self):
        self.view.clear()
        self.view.set_background("#12151c", top="#2c384c")
        self.hint.show()
        self.hint.raise_()

    def _frame_model(self):
        self._axis = None
        self._axis_flip = False
        self._mark_axis_button()
        try:
            self.view.disable_parallel_projection()
        except Exception:
            pass
        self.view.view_isometric()
        self.view.reset_camera()
        self.view.render()

    def _apply_axis_view(self):
        # Look from the positive axis first. Y uses the opposite preset so +Y stays upright.
        methods = {
            "x": ("view_yz", False),
            "y": ("view_xz", True),
            "z": ("view_xy", False),
        }
        method_name, base_negative = methods[self._axis or "z"]
        try:
            self.view.enable_parallel_projection()
        except Exception:
            pass
        getattr(self.view, method_name)(negative=base_negative ^ self._axis_flip)
        self.view.render()

    def _mark_axis_button(self):
        self._view_group.setExclusive(False)
        for axis, button in self.view_buttons.items():
            active = axis == self._axis
            button.setChecked(active)
            button.setText(f"{'-' if active and self._axis_flip else ''}{axis.upper()}")
        self._view_group.setExclusive(True)

    def _apply_camera_style(self):
        interactor = getattr(self.view, "iren", None)
        if interactor is None or getattr(interactor, "interactor", None) is None:
            return
        self._style = InspectStyle()
        try:
            interactor.style = self._style
        except Exception:
            return

    def _set_busy(self, busy: bool):
        self.open_button.setEnabled(not busy)
        self.snapshot_button.setEnabled((not busy) and self._model is not None)
        self.reset_button.setEnabled((not busy) and self._model is not None)
        for button in self.view_buttons.values():
            button.setEnabled((not busy) and self._model is not None)
        self.edges_button.setEnabled(not busy)
        if busy and not self._cursor_pushed:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self._cursor_pushed = True
        elif not busy and self._cursor_pushed:
            QApplication.restoreOverrideCursor()
            self._cursor_pushed = False


def _polydata(part: MeshPart) -> pv.PolyData:
    packed = np.empty((len(part.faces), 4), dtype=np.int64)
    packed[:, 0] = 3
    packed[:, 1:] = part.faces
    mesh = pv.PolyData(np.ascontiguousarray(part.vertices), np.ascontiguousarray(packed).ravel())
    if part.normals is not None and len(part.normals) == mesh.n_points:
        mesh.point_data["Normals"] = part.normals
    else:
        try:
            mesh.compute_normals(
                cell_normals=False,
                point_normals=True,
                inplace=True,
                consistent_normals=False,
            )
        except Exception:
            pass
    return mesh


def _dropped_model(event) -> str | None:
    mime = event.mimeData()
    if mime is None or not mime.hasUrls():
        return None
    for url in mime.urls():
        local = url.toLocalFile()
        if local and Path(local).is_file() and is_supported(local):
            return local
    return None


def _with_image_suffix(path: str, selected_filter: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        return path
    if "JPEG" in selected_filter or "jpg" in selected_filter.lower():
        return str(Path(path).with_suffix(".jpg"))
    return str(Path(path).with_suffix(".png"))


def _save_image(path: str, image) -> None:
    array = np.ascontiguousarray(image)
    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise RuntimeError("渲染结果不是一张图片。")
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
        array = np.ascontiguousarray(array)

    height, width = array.shape[:2]
    if array.shape[2] == 3:
        image_format = QImage.Format.Format_RGB888
        stride = 3 * width
    else:
        image_format = QImage.Format.Format_RGBA8888
        stride = 4 * width
    picture = QImage(array.data, width, height, stride, image_format).copy()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if not picture.save(path):
        raise RuntimeError(path)


def _app_icon() -> QIcon:
    icon_path = _resource_path("icon.ico")
    if icon_path.is_file():
        return QIcon(str(icon_path))
    return QIcon()


def _resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    app = QApplication(sys.argv)
    app.setApplicationName("3D 模型预览")
    app.setStyle("Fusion")
    app.setWindowIcon(_app_icon())
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(_STYLESHEET)
    window = MainWindow()
    window.show()
    if args:
        window.open_path(args[0])
    return app.exec()


_STYLESHEET = """
QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI";
}
QMainWindow, QWidget#central, QWidget#spacer {
    background: #101218;
    color: #e8eaed;
}
QToolBar {
    background: #181b22;
    border: none;
    border-bottom: 1px solid #2a2f3a;
    spacing: 8px;
    padding: 8px 10px;
}
QToolBar::separator {
    background: #2a2f3a;
    width: 1px;
    margin: 6px 8px;
}
QLabel#appTitle {
    color: #f3f5f8;
    font-size: 15px;
    font-weight: 600;
    padding: 0 8px 0 4px;
}
QPushButton {
    background: #262b36;
    color: #e8eaed;
    border: 1px solid #343a48;
    border-radius: 8px;
    padding: 6px 14px;
    min-height: 20px;
}
QPushButton:hover { background: #323846; }
QPushButton:pressed { background: #2a63d6; }
QPushButton:disabled { color: #6d7583; background: #1b1f27; border-color: #2a2f3a; }
QPushButton#primary {
    background: #3d8bfd;
    border-color: #3d8bfd;
    color: white;
    font-weight: 600;
}
QPushButton#primary:hover { background: #5b9dff; }
QPushButton:checked {
    background: #2f6fed;
    border-color: #2f6fed;
    color: white;
}
QLabel#viewLabel {
    color: #9aa3b2;
    padding: 0 2px 0 6px;
}
QPushButton#axisView {
    min-width: 36px;
    padding: 6px 8px;
    font-weight: 600;
}
QWidget#dropHint { background: transparent; }
QLabel#dropCard {
    color: #d5dbe6;
    background: rgba(22, 26, 34, 210);
    border: 1.5px dashed #465068;
    border-radius: 18px;
    padding: 36px 28px;
    font-size: 18px;
}
QStatusBar {
    background: #181b22;
    color: #9aa3b2;
    border-top: 1px solid #2a2f3a;
}
QStatusBar QLabel { color: #9aa3b2; padding: 0 8px; }
"""


if __name__ == "__main__":
    raise SystemExit(main())
