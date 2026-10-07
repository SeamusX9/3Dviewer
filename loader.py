"""Load GLB, FBX, OBJ, STL, 3DS/3D and SKP files into triangle meshes."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SUPPORTED_EXTENSIONS = {
    ".glb",
    ".gltf",
    ".fbx",
    ".obj",
    ".stl",
    ".3ds",
    ".3d",
    ".skp",
}

FILE_FILTER = (
    "3D 模型 (*.glb *.gltf *.fbx *.obj *.stl *.3ds *.3d *.skp);;"
    "glTF / GLB (*.glb *.gltf);;"
    "FBX (*.fbx);;"
    "Wavefront OBJ (*.obj);;"
    "STL (*.stl);;"
    "3D / 3DS (*.3ds *.3d);;"
    "SketchUp (*.skp);;"
    "所有文件 (*.*)"
)

_ASSIMP_EXTS = {".fbx", ".obj", ".stl", ".3ds", ".3d"}
_TRIMESH_EXTS = {".glb", ".gltf", ".obj", ".stl"}


class ModelLoadError(Exception):
    """Raised when a file cannot be turned into a preview mesh."""


@dataclass
class MeshPart:
    vertices: np.ndarray
    faces: np.ndarray
    color: tuple[float, float, float] | None = None
    vertex_colors: np.ndarray | None = None
    normals: np.ndarray | None = None


@dataclass
class LoadedModel:
    path: str
    parts: list[MeshPart] = field(default_factory=list)

    @property
    def vertex_count(self) -> int:
        return int(sum(len(part.vertices) for part in self.parts))

    @property
    def face_count(self) -> int:
        return int(sum(len(part.faces) for part in self.parts))


def is_supported(path: str | os.PathLike[str]) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def load_model(path: str | os.PathLike[str]) -> LoadedModel:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ModelLoadError(f"找不到文件：{source}")

    ext = source.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        shown = ext or "（无扩展名）"
        raise ModelLoadError(
            f"不支持的格式 {shown}。\n支持：GLB、GLTF、FBX、OBJ、STL、3DS、3D、SKP。"
        )

    try:
        if ext == ".skp":
            parts = _load_skp(source)
        elif ext in _TRIMESH_EXTS:
            parts = _load_with_fallback(source, ext)
        else:
            parts = _load_assimp(source)
    except ModelLoadError:
        raise
    except Exception as exc:
        raise ModelLoadError(f"无法读取该模型：{exc}") from exc

    parts = _prepare_parts(parts)
    if not parts:
        raise ModelLoadError("文件里没有可显示的三角面。")
    return LoadedModel(path=str(source), parts=parts)


def _load_with_fallback(source: Path, ext: str) -> list[MeshPart]:
    error: Exception | None = None
    try:
        parts = _load_trimesh(source)
    except Exception as exc:
        parts = []
        error = exc
    if parts:
        return parts
    if ext in _ASSIMP_EXTS:
        return _load_assimp(source)
    if error is not None:
        raise error
    return []


def _prepare_parts(parts: list[MeshPart]) -> list[MeshPart]:
    cleaned: list[MeshPart] = []
    for part in parts:
        sanitized = _sanitize_part(part)
        if sanitized is not None:
            cleaned.append(sanitized)
    return _merge_parts(cleaned)


def _sanitize_part(part: MeshPart) -> MeshPart | None:
    vertices = np.asarray(part.vertices, dtype=np.float64)
    faces = np.asarray(part.faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        return None
    if len(vertices) < 3 or len(faces) < 1:
        return None

    vertices = np.nan_to_num(vertices, nan=0.0, posinf=0.0, neginf=0.0)
    limit = len(vertices)
    valid = np.all((faces >= 0) & (faces < limit), axis=1)
    valid &= (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    faces = np.ascontiguousarray(faces[valid])
    if len(faces) == 0:
        return None

    normals = part.normals
    if normals is not None:
        normals = np.asarray(normals, dtype=np.float64)
        if normals.shape != vertices.shape or not np.isfinite(normals).all():
            normals = None

    vertex_colors = part.vertex_colors
    if vertex_colors is not None:
        vertex_colors = np.asarray(vertex_colors)
        if vertex_colors.shape[0] != len(vertices) or vertex_colors.shape[1] < 3:
            vertex_colors = None
        else:
            vertex_colors = np.ascontiguousarray(vertex_colors[:, :3].astype(np.uint8))

    return MeshPart(
        vertices=np.ascontiguousarray(vertices),
        faces=faces,
        color=part.color,
        vertex_colors=vertex_colors,
        normals=None if normals is None else np.ascontiguousarray(normals),
    )


def _merge_parts(parts: list[MeshPart]) -> list[MeshPart]:
    """Combine same-colored parts so large SketchUp files stay interactive."""
    groups: dict[tuple, list[MeshPart]] = {}
    order: list[tuple] = []
    for part in parts:
        if part.vertex_colors is not None:
            key: tuple = ("vertex",)
        else:
            color = None if part.color is None else tuple(round(channel, 3) for channel in part.color)
            key = ("solid", color)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(part)

    merged: list[MeshPart] = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            merged.append(group[0])
            continue
        merged.append(_concatenate(group))
    return merged


def _concatenate(group: list[MeshPart]) -> MeshPart:
    vertices = []
    faces = []
    normals = []
    colors = []
    offset = 0
    keep_normals = all(part.normals is not None for part in group)
    keep_colors = all(part.vertex_colors is not None for part in group)
    for part in group:
        vertices.append(part.vertices)
        faces.append(part.faces + offset)
        if keep_normals and part.normals is not None:
            normals.append(part.normals)
        if keep_colors and part.vertex_colors is not None:
            colors.append(part.vertex_colors)
        offset += len(part.vertices)
    return MeshPart(
        vertices=np.vstack(vertices),
        faces=np.vstack(faces),
        color=group[0].color,
        vertex_colors=np.vstack(colors) if keep_colors else None,
        normals=np.vstack(normals) if keep_normals else None,
    )


def _load_skp(path: Path) -> list[MeshPart]:
    try:
        from openskp import SkpFile
    except ImportError as exc:
        raise ModelLoadError("缺少 openskp，无法打开 SKP 文件。请先安装依赖。") from exc

    skp = SkpFile.open(str(path))
    fd, temp_name = tempfile.mkstemp(suffix=".glb")
    os.close(fd)
    try:
        from openskp.export import glb as glb_export

        if hasattr(skp, "parse"):
            skp.parse()
        try:
            glb_export.export(skp, temp_name, textures=True)
        except TypeError:
            glb_export.export(skp, temp_name)
        if os.path.getsize(temp_name) <= 0:
            raise ModelLoadError("SKP 转换结果为空。")
        parts = _load_trimesh(Path(temp_name))
        if parts:
            return parts
        raise ModelLoadError("SKP 转换后没有三角面。")
    except ModelLoadError:
        raise
    except Exception:
        if hasattr(skp, "build_scene"):
            return _parts_from_skp_scene(skp.build_scene())
        raise
    finally:
        try:
            os.remove(temp_name)
        except OSError:
            pass


def _parts_from_skp_scene(scene) -> list[MeshPart]:
    primitives = getattr(scene, "glb_primitives", None) or []
    parts: list[MeshPart] = []
    for primitive in primitives:
        vertices = _as_vectors(getattr(primitive, "positions", None))
        faces = _as_triangles(getattr(primitive, "indices", None))
        if vertices is None or faces is None:
            continue
        color = _primitive_color(scene, primitive)
        normals = _as_vectors(getattr(primitive, "normals", None))
        parts.append(MeshPart(vertices, faces, color=color, normals=normals))
    return parts


def _primitive_color(scene, primitive) -> tuple[float, float, float] | None:
    materials = getattr(scene, "gltf_materials", None) or []
    index = getattr(primitive, "material_index", None)
    if index is not None and 0 <= int(index) < len(materials):
        material = materials[int(index)]
        if isinstance(material, dict):
            pbr = material.get("pbrMetallicRoughness", {})
            if isinstance(pbr, dict):
                color = _color_tuple(pbr.get("baseColorFactor"))
                if color is not None:
                    return color
    for attr in ("color", "base_color", "baseColorFactor", "diffuse"):
        color = _color_tuple(getattr(primitive, attr, None))
        if color is not None:
            return color
    return None


def _load_trimesh(path: Path) -> list[MeshPart]:
    try:
        import trimesh
    except ImportError as exc:
        raise ModelLoadError("缺少 trimesh，无法打开该模型。请先安装依赖。") from exc

    loaded = trimesh.load(str(path), force="scene", process=False)
    geometries = _scene_geometries(loaded)
    parts = [_part_from_trimesh(geom, index) for index, geom in enumerate(geometries)]
    parts = [part for part in parts if part is not None]
    if parts:
        return parts

    fallback = trimesh.load(str(path), force="mesh", process=True)
    part = _part_from_trimesh(fallback, 0)
    return [] if part is None else [part]


def _scene_geometries(loaded):
    import trimesh

    if isinstance(loaded, trimesh.Trimesh):
        return [loaded]
    if not isinstance(loaded, trimesh.Scene):
        return []

    try:
        dumped = loaded.dump(concatenate=False)
    except Exception:
        dumped = None
    if dumped:
        return [geom for geom in dumped if isinstance(geom, trimesh.Trimesh)]

    geometries = []
    graph = getattr(loaded, "graph", None)
    nodes = getattr(graph, "nodes_geometry", []) if graph is not None else []
    for node_name in nodes:
        transform, geom_name = loaded.graph[node_name]
        geom = loaded.geometry[geom_name].copy()
        geom.apply_transform(transform)
        geometries.append(geom)
    if not geometries:
        geometries.extend(
            geom for geom in loaded.geometry.values() if isinstance(geom, trimesh.Trimesh)
        )
    return geometries


def _part_from_trimesh(geom, index: int) -> MeshPart | None:
    import trimesh

    if not isinstance(geom, trimesh.Trimesh):
        return None
    if geom.vertices is None or geom.faces is None or len(geom.vertices) < 3 or len(geom.faces) < 1:
        return None

    vertices = np.asarray(geom.vertices, dtype=np.float64)
    faces = np.asarray(geom.faces, dtype=np.int64)
    return MeshPart(
        vertices=vertices,
        faces=faces,
        color=_trimesh_color(geom),
        vertex_colors=_trimesh_vertex_colors(geom),
    )


def _trimesh_color(geom) -> tuple[float, float, float] | None:
    visual = getattr(geom, "visual", None)
    if visual is None:
        return None

    material = getattr(visual, "material", None)
    if material is not None:
        for attr in ("baseColorFactor", "main_color", "diffuse"):
            color = _color_tuple(getattr(material, attr, None))
            if color is not None:
                return color

    if getattr(visual, "kind", None) == "face":
        face_colors = np.asarray(getattr(visual, "face_colors", []))
        if face_colors.size >= 3:
            return _color_tuple(face_colors[:, :3].mean(axis=0))
    if getattr(visual, "kind", None) == "vertex":
        vertex_colors = np.asarray(getattr(visual, "vertex_colors", []))
        if vertex_colors.size >= 3:
            return _color_tuple(vertex_colors[:, :3].mean(axis=0))
    return None


def _trimesh_vertex_colors(geom) -> np.ndarray | None:
    visual = getattr(geom, "visual", None)
    if visual is None or getattr(visual, "kind", None) != "vertex":
        return None
    colors = np.asarray(getattr(visual, "vertex_colors", []))
    if colors.ndim != 2 or colors.shape[0] != len(geom.vertices) or colors.shape[1] < 3:
        return None
    rgb = colors[:, :3]
    if len(rgb) > 1 and rgb.min() == rgb.max():
        return None
    return rgb.astype(np.uint8)


def _load_assimp(path: Path) -> list[MeshPart]:
    try:
        import assimp_py
    except ImportError as exc:
        raise ModelLoadError("缺少 assimp-py，无法打开该模型。请先安装依赖。") from exc

    flags = _assimp_flags(assimp_py)
    scene = _import_assimp(assimp_py, path, flags)
    meshes = list(getattr(scene, "meshes", []) or [])
    if not meshes:
        raise ModelLoadError("这个文件没有网格数据。")

    pretransform = bool(getattr(assimp_py, "Process_PreTransformVertices", 0)) and (
        flags & int(assimp_py.Process_PreTransformVertices)
    )
    if pretransform or getattr(scene, "root_node", None) is None:
        return [_part_from_assimp(scene, mesh, np.eye(4)) for mesh in meshes]

    parts: list[MeshPart] = []
    _collect_node_meshes(scene, scene.root_node, np.eye(4), parts)
    if parts:
        return parts
    return [_part_from_assimp(scene, mesh, np.eye(4)) for mesh in meshes]


def _assimp_flags(assimp_py) -> int:
    names = ["Process_Triangulate", "Process_JoinIdenticalVertices", "Process_PreTransformVertices"]
    if hasattr(assimp_py, "Process_GenSmoothNormals"):
        names.append("Process_GenSmoothNormals")
    elif hasattr(assimp_py, "Process_GenNormals"):
        names.append("Process_GenNormals")
    flags = 0
    for name in names:
        flags |= int(getattr(assimp_py, name, 0) or 0)
    return flags


def _import_assimp(assimp_py, path: Path, flags: int):
    importer = getattr(assimp_py, "import_file", None) or getattr(assimp_py, "ImportFile", None)
    if importer is None:
        raise ModelLoadError("当前 assimp-py 没有可用的导入函数。")

    try:
        return importer(str(path), flags)
    except Exception:
        if str(path).isascii():
            raise
        fd, temp_name = tempfile.mkstemp(suffix=path.suffix)
        os.close(fd)
        try:
            import shutil

            shutil.copy2(path, temp_name)
            return importer(temp_name, flags)
        finally:
            try:
                os.remove(temp_name)
            except OSError:
                pass


def _collect_node_meshes(scene, node, parent: np.ndarray, parts: list[MeshPart]) -> None:
    if node is None:
        return
    world = parent @ _matrix4(getattr(node, "transformation", None))
    meshes = list(getattr(scene, "meshes", []) or [])
    for mesh_id in _node_mesh_ids(node):
        if 0 <= mesh_id < len(meshes):
            parts.append(_part_from_assimp(scene, meshes[mesh_id], world))
    for child in getattr(node, "children", []) or []:
        _collect_node_meshes(scene, child, world, parts)


def _node_mesh_ids(node) -> list[int]:
    for attr in ("meshes", "mesh_indices", "mesh_indexes"):
        value = getattr(node, attr, None)
        if value:
            return [int(item) for item in value]
    return []


def _matrix4(raw) -> np.ndarray:
    if raw is None:
        return np.eye(4)
    matrix = np.asarray(raw, dtype=np.float64)
    if matrix.shape == (4, 4):
        return matrix
    if matrix.size == 16:
        return matrix.reshape(4, 4)
    return np.eye(4)


def _part_from_assimp(scene, mesh, transform: np.ndarray) -> MeshPart:
    vertices = _as_vectors(getattr(mesh, "vertices", None))
    faces = _as_triangles(getattr(mesh, "indices", None))
    if faces is None:
        faces = _as_triangles(getattr(mesh, "faces", None))
    if vertices is None or faces is None:
        return MeshPart(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))

    if not np.allclose(transform, np.eye(4)):
        vertices = _apply_transform(vertices, transform)

    normals = _as_vectors(getattr(mesh, "normals", None))
    if normals is not None and len(normals) != len(vertices):
        normals = None
    elif normals is not None and not np.allclose(transform, np.eye(4)):
        linear = transform[:3, :3]
        try:
            normal_matrix = np.linalg.inv(linear).T
            normals = normals @ normal_matrix.T
            lengths = np.linalg.norm(normals, axis=1, keepdims=True)
            normals = normals / np.clip(lengths, 1e-8, None)
        except np.linalg.LinAlgError:
            normals = None

    return MeshPart(
        vertices=vertices,
        faces=faces,
        color=_assimp_color(scene, mesh),
        vertex_colors=_assimp_vertex_colors(mesh, len(vertices)),
        normals=normals,
    )


def _apply_transform(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    homogeneous = np.ones((len(points), 4), dtype=np.float64)
    homogeneous[:, :3] = points
    return (homogeneous @ matrix.T)[:, :3]


def _assimp_color(scene, mesh) -> tuple[float, float, float] | None:
    materials = getattr(scene, "materials", None) or []
    index = getattr(mesh, "material_index", None)
    if index is None or not (0 <= int(index) < len(materials)):
        return None
    material = materials[int(index)]
    if not isinstance(material, dict):
        material = getattr(material, "__dict__", {})
    if not isinstance(material, dict):
        return None
    for key in ("COLOR_DIFFUSE", "BASE_COLOR", "COLOR_AMBIENT"):
        color = _color_tuple(material.get(key))
        if color is not None and max(color) > 0.02:
            return color
    return None


def _assimp_vertex_colors(mesh, count: int) -> np.ndarray | None:
    colors = getattr(mesh, "colors", None)
    if not colors:
        return None
    array = np.asarray(colors[0], dtype=np.float64)
    if array.size == 0:
        return None
    if array.ndim == 1:
        width = 4 if array.size % 4 == 0 else 3
        if array.size % width != 0:
            return None
        array = array.reshape(-1, width)
    if len(array) != count:
        return None
    rgb = array[:, :3]
    if rgb.max(initial=0) <= 1.5:
        rgb = np.clip(rgb, 0.0, 1.0) * 255.0
    return rgb.astype(np.uint8)


def _as_vectors(data) -> np.ndarray | None:
    if data is None:
        return None
    try:
        array = np.asarray(data, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if array.size == 0:
        return None
    if array.ndim == 1:
        if array.size % 3 != 0:
            return None
        array = array.reshape(-1, 3)
    elif array.shape[-1] != 3:
        if array.size % 3 != 0:
            return None
        array = array.reshape(-1, 3)
    else:
        array = array.reshape(-1, 3)
    return array


def _as_triangles(data) -> np.ndarray | None:
    if data is None:
        return None
    if isinstance(data, (list, tuple)) and data and isinstance(data[0], (list, tuple, np.ndarray)):
        try:
            faces = np.asarray(data, dtype=np.int64)
        except ValueError:
            flattened = [int(index) for face in data for index in face]
            if not flattened or len(flattened) % 3 != 0:
                return None
            faces = np.asarray(flattened, dtype=np.int64).reshape(-1, 3)
    else:
        try:
            faces = np.asarray(data, dtype=np.int64)
        except (TypeError, ValueError):
            return None
    if faces.size == 0:
        return None
    if faces.ndim == 1:
        if faces.size % 3 != 0:
            return None
        faces = faces.reshape(-1, 3)
    elif faces.shape[-1] == 4:
        triangles = np.vstack([faces[:, [0, 1, 2]], faces[:, [0, 2, 3]]])
        faces = triangles
    elif faces.shape[-1] != 3:
        if faces.size % 3 != 0:
            return None
        faces = faces.reshape(-1, 3)
    else:
        faces = faces.reshape(-1, 3)
    return faces


def _color_tuple(value) -> tuple[float, float, float] | None:
    if value is None:
        return None
    try:
        array = np.asarray(value, dtype=np.float64).ravel()
    except (TypeError, ValueError):
        return None
    if array.size < 3 or not np.isfinite(array[:3]).all():
        return None
    rgb = array[:3].astype(np.float64, copy=True)
    if float(rgb.max()) > 1.5:
        rgb /= 255.0
    rgb = np.clip(rgb, 0.0, 1.0)
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]))
