"""Draw the wireframe-cube application icon."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
LINE = (236, 242, 255, 255)
BACKGROUND = (24, 32, 48, 255)


def _project(x: float, y: float, z: float, size: float) -> tuple[float, float]:
    scale = size * 0.20
    sx = (x - z) * math.cos(math.radians(30))
    sy = y * 0.92 + (x + z) * 0.5
    return size / 2 + sx * scale, size * 0.54 - sy * scale


def _edges():
    corners = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    found = []
    for index, start in enumerate(corners):
        for end in corners[index + 1 :]:
            if sum(abs(a - b) for a, b in zip(start, end)) == 2:
                found.append((start, end))
    return found


def draw_icon(size: int) -> Image.Image:
    scale = 4
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(scale, canvas // 28)
    radius = max(scale * 2, canvas // 6)
    draw.rounded_rectangle(
        (margin, margin, canvas - 1 - margin, canvas - 1 - margin),
        radius=radius,
        fill=BACKGROUND,
    )

    points = {corner: _project(*corner, canvas) for corner in [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]}
    width = max(scale, round(canvas * 0.028))
    radius_px = width / 2
    for start, end in _edges():
        p1 = points[start]
        p2 = points[end]
        draw.line((p1, p2), fill=LINE, width=width)
        for point in (p1, p2):
            draw.ellipse(
                (
                    point[0] - radius_px,
                    point[1] - radius_px,
                    point[0] + radius_px,
                    point[1] + radius_px,
                ),
                fill=LINE,
            )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = [draw_icon(size) for size in sizes]
    images[-1].save(ROOT / "icon-preview.png")
    images[0].save(
        ROOT / "icon.ico",
        format="ICO",
        append_images=images[1:],
    )


if __name__ == "__main__":
    main()
