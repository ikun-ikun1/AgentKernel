"""Render architecture.mmd's production diagram without a browser runtime."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1800, 980
BG = "#f7f8fb"
CORE = "#e8f0fe"
STORAGE = "#fff4d6"
INK = "#1f2937"
EDGE = "#315ea8"
STORAGE_EDGE = "#a36b00"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _box(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], label: str, fill: str, outline: str) -> None:
    draw.rounded_rectangle(xy, radius=18, fill=fill, outline=outline, width=3)
    left, top, right, bottom = xy
    lines = label.split("\n")
    font = _font(25)
    line_height = 34
    total_height = line_height * len(lines)
    y = (top + bottom - total_height) // 2
    for line in lines:
        bounds = draw.textbbox((0, 0), line, font=font)
        x = (left + right - (bounds[2] - bounds[0])) // 2
        draw.text((x, y), line, fill=INK, font=font)
        y += line_height


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], dashed: bool = False) -> None:
    if dashed:
        x1, y1 = start
        x2, y2 = end
        steps = max(abs(x2 - x1), abs(y2 - y1)) // 18
        for index in range(max(1, steps)):
            if index % 2 == 0:
                a = index / max(1, steps)
                b = min(1, (index + 1) / max(1, steps))
                draw.line((x1 + (x2 - x1) * a, y1 + (y2 - y1) * a,
                           x1 + (x2 - x1) * b, y1 + (y2 - y1) * b), fill=EDGE, width=3)
    else:
        draw.line((*start, *end), fill=EDGE, width=4)
    x, y = end
    draw.polygon([(x, y), (x - 14, y - 8), (x - 14, y + 8)], fill=EDGE)


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    title_font = _font(38)
    draw.text((60, 35), "AgentKernel: Runtime + Production RAG Infrastructure", fill=INK, font=title_font)

    boxes = {
        "user": (60, 410, 270, 510, "CLI / MCP Host", CORE, EDGE),
        "agent": (350, 370, 650, 550, "Agent Runtime\nReAct + Context", CORE, EDGE),
        "llm": (350, 120, 650, 245, "LLM Adapter\nOpenAI-compatible", CORE, EDGE),
        "registry": (350, 675, 650, 800, "Tool Registry\nContract + Schema", CORE, EDGE),
        "client": (760, 675, 1060, 800, "MCP Client\nJSON-RPC + stdio", CORE, EDGE),
        "server": (1170, 675, 1470, 800, "MCP Server\nRead-only tools", CORE, EDGE),
        "rag": (1170, 370, 1470, 550, "RAG Pipeline\nIngest + Hybrid Search", CORE, EDGE),
        "catalog": (1540, 265, 1740, 390, "SQLite\nCatalog + FTS5", STORAGE, STORAGE_EDGE),
        "vector": (1540, 465, 1740, 590, "Chroma\nOptional vectors", STORAGE, STORAGE_EDGE),
        "source": (1540, 680, 1740, 805, "PDF / MD / TXT", STORAGE, STORAGE_EDGE),
        "memory": (760, 120, 1060, 245, "SQLite Runtime Store\nSessions + Logs", STORAGE, STORAGE_EDGE),
    }
    for left, top, right, bottom, label, fill, outline in boxes.values():
        _box(draw, (left, top, right, bottom), label, fill, outline)

    _arrow(draw, (270, 460), (350, 460))
    _arrow(draw, (500, 370), (500, 245))
    _arrow(draw, (650, 460), (760, 730))
    _arrow(draw, (650, 460), (500, 675))
    _arrow(draw, (1060, 730), (1170, 730))
    _arrow(draw, (1320, 675), (1320, 550))
    _arrow(draw, (1540, 742), (1470, 500))
    _arrow(draw, (1470, 420), (1540, 330))
    _arrow(draw, (1470, 500), (1540, 525), dashed=True)
    _arrow(draw, (650, 250), (760, 180), dashed=True)

    note_font = _font(18)
    draw.text((620, 880), "Durable lexical baseline | Optional semantic index | Citations retain source/page metadata", fill=INK, font=note_font)
    output = Path(__file__).with_name("architecture.png")
    image.save(output, "PNG", optimize=True)
    print(output)


if __name__ == "__main__":
    main()
