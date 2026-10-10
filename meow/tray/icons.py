"""生成托盘/窗口用的猫头图标（.ico），不依赖 Pillow。

为什么要自己画：项目本来就能「下载即运行」，不应该为了一个图标引入
Pillow 这种重依赖。这里用纯 Python + ``zlib``/``struct`` 直接拼出
32 位 BMP 格式的 ICO —— 这种格式从 Windows XP 到 11 都被 ``LoadImage``
原生支持，比 PNG 压缩的 ICO 兼容性更好。

图标有两套配色：开启时是橘猫（睁眼），关闭时是灰猫（眯眼睡觉）。
生成结果缓存在 ``data/icons/`` 下，文件名带版本号，改画法时递增版本即可。
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

ICON_VERSION = 1
ICON_SIZE_LIST = (16, 32, 48, 64)
# 每个尺寸的超采样倍数（越大越平滑、越慢）
SUPERSAMPLE = {16: 4, 32: 3, 48: 2, 64: 2}

RGBA = tuple[int, int, int, int]

# ---------------- 几何常量（归一化坐标，y 轴向下）----------------

HEAD_CENTER = (0.5, 0.56)
HEAD_RADIUS = (0.38, 0.34)

EAR_TRIANGLES = (
    ((0.15, 0.46), (0.06, 0.05), (0.46, 0.26)),
    ((0.85, 0.46), (0.94, 0.05), (0.54, 0.26)),
)

EYE_LEFT = (0.355, 0.550)
EYE_RIGHT = (0.645, 0.550)
EYE_RADIUS = (0.062, 0.078)
EYE_HIGHLIGHT_OFFSET = (-0.020, -0.024)
EYE_HIGHLIGHT_RADIUS = 0.022

NOSE = ((0.44, 0.655), (0.56, 0.655), (0.50, 0.715))
NOSE_SCALE = 0.55

MOUTH_SEGMENTS = (
    ((0.50, 0.715), (0.50, 0.755)),
    ((0.50, 0.755), (0.435, 0.785)),
    ((0.50, 0.755), (0.565, 0.785)),
)
MOUTH_WIDTH = 0.016

# 睡觉时闭着的眼睛（横线）
CLOSED_EYE_SEGMENTS = (
    ((0.285, 0.565), (0.425, 0.545)),
    ((0.575, 0.545), (0.715, 0.565)),
)
CLOSED_EYE_WIDTH = 0.026

WHISKERS = (
    ((0.34, 0.680), (0.045, 0.600)),
    ((0.34, 0.725), (0.030, 0.725)),
    ((0.34, 0.770), (0.045, 0.850)),
    ((0.66, 0.680), (0.955, 0.600)),
    ((0.66, 0.725), (0.970, 0.725)),
    ((0.66, 0.770), (0.955, 0.850)),
)
WHISKER_WIDTH = 0.014

# 低于这个像素尺寸就省掉细节，避免糊成一团
DETAIL_MIN_SIZE = 32

OUTLINE_GROW = 0.030
OUTLINE_SHRINK = -0.008
EAR_INNER_SCALE = 0.52


@dataclass(frozen=True)
class Palette:
    """一套配色。"""

    fur: tuple[int, int, int]
    fur_shadow: tuple[int, int, int]
    outline: tuple[int, int, int]
    eye: tuple[int, int, int]
    eye_highlight: tuple[int, int, int]
    nose: tuple[int, int, int]
    whisker: tuple[int, int, int]


PALETTE_AWAKE = Palette(
    fur=(244, 166, 92),
    fur_shadow=(226, 143, 74),
    outline=(186, 108, 42),
    eye=(46, 42, 40),
    eye_highlight=(255, 252, 245),
    nose=(233, 118, 140),
    whisker=(255, 240, 224),
)

PALETTE_ASLEEP = Palette(
    fur=(170, 176, 184),
    fur_shadow=(150, 156, 164),
    outline=(116, 122, 130),
    eye=(94, 100, 108),
    eye_highlight=(255, 255, 255),
    nose=(196, 156, 164),
    whisker=(236, 238, 242),
)


# ==================== 几何工具 ====================


def _point_in_ellipse(x: float, y: float, cx: float, cy: float, rx: float, ry: float) -> bool:
    if rx <= 0 or ry <= 0:
        return False
    dx = (x - cx) / rx
    dy = (y - cy) / ry
    return dx * dx + dy * dy <= 1.0


def _point_in_triangle(px: float, py: float, a, b, c) -> bool:
    def sign(p1, p2, p3) -> float:
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1 = sign((px, py), a, b)
    d2 = sign((px, py), b, c)
    d3 = sign((px, py), c, a)
    has_negative = d1 < 0 or d2 < 0 or d3 < 0
    has_positive = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_negative and has_positive)


def _centroid(points) -> tuple[float, float]:
    count = len(points)
    return (
        sum(p[0] for p in points) / count,
        sum(p[1] for p in points) / count,
    )


def _grow_triangle(triangle, grow: float):
    cx, cy = _centroid(triangle)
    grown = []
    for x, y in triangle:
        dx, dy = x - cx, y - cy
        length = (dx * dx + dy * dy) ** 0.5 or 1.0
        grown.append((x + dx / length * grow, y + dy / length * grow))
    return tuple(grown)


def _scale_triangle(triangle, scale: float):
    cx, cy = _centroid(triangle)
    return tuple((cx + (x - cx) * scale, cy + (y - cy) * scale) for x, y in triangle)


def _distance_to_segment(px, py, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    proj_x, proj_y = ax + t * dx, ay + t * dy
    return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5


def _in_head_shape(x: float, y: float, grow: float = 0.0) -> bool:
    """猫头剪影 = 椭圆脸 + 两只三角耳。"""
    for triangle in EAR_TRIANGLES:
        if _point_in_triangle(x, y, *_grow_triangle(triangle, grow)):
            return True
    cx, cy = HEAD_CENTER
    rx, ry = HEAD_RADIUS
    return _point_in_ellipse(x, y, cx, cy, rx + grow, ry + grow)


def _in_ear(x: float, y: float) -> bool:
    return any(_point_in_triangle(x, y, *triangle) for triangle in EAR_TRIANGLES)


# ==================== 单点取色 ====================


def _sample(x: float, y: float, palette: Palette, awake: bool, detailed: bool) -> RGBA:
    """返回归一化坐标 (x, y) 处的颜色，透明用 alpha=0 表示。"""
    if not _in_head_shape(x, y):
        return (0, 0, 0, 0)

    # 轮廓：外扩一圈减去内缩一圈
    if _in_head_shape(x, y, OUTLINE_GROW) and not _in_head_shape(x, y, OUTLINE_SHRINK):
        return (*palette.outline, 255)

    # 耳朵内侧
    if detailed and _in_ear(x, y):
        for triangle in EAR_TRIANGLES:
            if _point_in_triangle(x, y, *_scale_triangle(triangle, EAR_INNER_SCALE)):
                return (*palette.fur_shadow, 255)

    color = palette.fur

    # 眼睛
    if awake:
        for cx, cy in (EYE_LEFT, EYE_RIGHT):
            if _point_in_ellipse(x, y, cx, cy, *EYE_RADIUS):
                color = palette.eye
            if _point_in_ellipse(
                x,
                y,
                cx + EYE_HIGHLIGHT_OFFSET[0],
                cy + EYE_HIGHLIGHT_OFFSET[1],
                EYE_HIGHLIGHT_RADIUS,
                EYE_HIGHLIGHT_RADIUS,
            ):
                return (*palette.eye_highlight, 255)
    else:
        for start, end in CLOSED_EYE_SEGMENTS:
            if _distance_to_segment(x, y, start, end) <= CLOSED_EYE_WIDTH / 2:
                color = palette.eye

    # 鼻子
    if _point_in_triangle(x, y, *NOSE):
        color = palette.nose

    # 嘴（小 ω）
    if detailed:
        for start, end in MOUTH_SEGMENTS:
            if _distance_to_segment(x, y, start, end) <= MOUTH_WIDTH / 2:
                color = palette.outline

    # 胡须
    if detailed:
        for start, end in WHISKERS:
            if _distance_to_segment(x, y, start, end) <= WHISKER_WIDTH / 2:
                return (*palette.whisker, 255)

    return (*color, 255)


# ==================== 渲染 ====================


def render_icon(awake: bool, size: int) -> list[list[RGBA]]:
    """渲染一张 ``size × size`` 的图标，返回自上而下的 RGBA 行。"""
    palette = PALETTE_AWAKE if awake else PALETTE_ASLEEP
    samples = SUPERSAMPLE.get(size, 2)
    detailed = size >= DETAIL_MIN_SIZE
    step = 1.0 / (size * samples)
    total = samples * samples

    rows: list[list[RGBA]] = []
    for pixel_y in range(size):
        row: list[RGBA] = []
        for pixel_x in range(size):
            sum_r = sum_g = sum_b = sum_a = 0.0
            for sub_y in range(samples):
                y = (pixel_y * samples + sub_y + 0.5) * step
                for sub_x in range(samples):
                    x = (pixel_x * samples + sub_x + 0.5) * step
                    r, g, b, a = _sample(x, y, palette, awake, detailed)
                    if a:
                        # 在「预乘 alpha」空间累加，避免边缘出现黑边
                        weight = a / 255.0
                        sum_r += r * weight
                        sum_g += g * weight
                        sum_b += b * weight
                        sum_a += weight
            if sum_a <= 0:
                row.append((0, 0, 0, 0))
                continue
            alpha = sum_a / total
            row.append(
                (
                    int(round(sum_r / sum_a)),
                    int(round(sum_g / sum_a)),
                    int(round(sum_b / sum_a)),
                    int(round(alpha * 255)),
                )
            )
        rows.append(row)
    return rows


# ==================== ICO 编码 ====================


def _bmp_image(rows: list[list[RGBA]]) -> bytes:
    """把像素打成 ICO 内嵌的 32 位 BMP（BITMAPINFOHEADER + XOR + AND）。"""
    size = len(rows)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        size,        # biWidth
        size * 2,    # biHeight：XOR 图 + AND 掩码两倍高
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression = BI_RGB
        size * size * 4,
        0, 0, 0, 0,
    )

    xor = bytearray()
    for y in range(size - 1, -1, -1):  # BMP 自下而上存储
        for x in range(size):
            r, g, b, a = rows[y][x]
            xor += bytes((b, g, r, a))

    row_bytes = ((size + 31) // 32) * 4
    mask = bytearray()
    for y in range(size - 1, -1, -1):
        bits = bytearray(row_bytes)
        for x in range(size):
            if rows[y][x][3] < 128:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask += bits

    return header + bytes(xor) + bytes(mask)


def encode_ico(images: dict[int, list[list[RGBA]]]) -> bytes:
    """把 ``{尺寸: 像素}`` 编码成 .ico 文件内容。"""
    sizes = sorted(images)
    payloads = [(size, _bmp_image(images[size])) for size in sizes]

    directory = struct.pack("<HHH", 0, 1, len(payloads))
    offset = 6 + 16 * len(payloads)
    entries = bytearray()
    for size, data in payloads:
        dimension = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII",
            dimension, dimension,
            0, 0,          # 调色板数量、保留位
            1, 32,         # 平面数、位深
            len(data), offset,
        )
        offset += len(data)
    return bytes(directory + entries) + b"".join(data for _, data in payloads)


# ==================== 对外接口 ====================


def icon_filename(awake: bool) -> str:
    state = "on" if awake else "off"
    return f"cat-{state}-v{ICON_VERSION}.ico"


def build_ico(awake: bool, sizes: tuple[int, ...] = ICON_SIZE_LIST) -> bytes:
    images = {size: render_icon(awake, size) for size in sizes}
    return encode_ico(images)


def ensure_icons(icon_dir: Path, *, force: bool = False) -> dict[str, Path]:
    """确保两套图标都存在，返回 ``{"on": path, "off": path}``。"""
    icon_dir = Path(icon_dir)
    icon_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    for awake, key in ((True, "on"), (False, "off")):
        target = icon_dir / icon_filename(awake)
        if force or not target.exists() or target.stat().st_size == 0:
            LOGGER.info("生成图标：%s", target.name)
            target.write_bytes(build_ico(awake))
        paths[key] = target
    return paths
