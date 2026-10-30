"""Render architecture.mmd's layered boundary diagram without a browser runtime."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1800, 850
BG = "#f7f8fb"
CORE = "#e8f0fe"
APP = "#eaf7ea"
PORT = "#fff4d6"
ADAPTER = "#f3e8ff"
EXTERNAL = "#ffffff"
INK = "#1f2937"
EDGE = "#315ea8"
MUTED = "#cbd5e1"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _box(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], label: str, fill: str, outline: str
) -> None:
    draw.rounded_rectangle(xy, radius=14, fill=fill, outline=outline, width=2)
    left, top, right, bottom = xy
    lines = label.split("\n")
    font = _font(20)
    line_height = 28
    y = (top + bottom - line_height * len(lines)) // 2
    for line in lines:
        bounds = draw.textbbox((0, 0), line, font=font)
        x = (left + right - (bounds[2] - bounds[0])) // 2
        draw.text((x, y), line, fill=INK, font=font)
        y += line_height


def _band(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], title: str, fill: str, outline: str
) -> None:
    draw.rounded_rectangle(xy, radius=20, fill=fill, outline=outline, width=2)
    draw.text((xy[0] + 18, xy[1] + 8), title, fill=INK, font=_font(24))


def _arrow(
    draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], dashed: bool = False
) -> None:
    if dashed:
        x1, y1 = start
        x2, y2 = end
        steps = max(abs(x2 - x1), abs(y2 - y1)) // 16
        for index in range(max(1, steps)):
            if index % 2 == 0:
                a = index / max(1, steps)
                b = min(1, (index + 1) / max(1, steps))
                draw.line(
                    (
                        x1 + (x2 - x1) * a,
                        y1 + (y2 - y1) * a,
                        x1 + (x2 - x1) * b,
                        y1 + (y2 - y1) * b,
                    ),
                    fill=EDGE,
                    width=2,
                )
    else:
        draw.line((*start, *end), fill=EDGE, width=3)
    x, y = end
    draw.polygon([(x, y), (x - 11, y - 7), (x - 11, y + 7)], fill=EDGE)


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.text((60, 28), "AgentKernel: Ports & Adapters Boundaries", fill=INK, font=_font(38))
    draw.text(
        (60, 72),
        "CLI -> Application -> Ports <- Adapters -> external systems; legacy import shims kept for one release",
        fill="#4b5563",
        font=_font(19),
    )

    bands = [
        ((60, 110, 1180, 225), "CLI / Composition Root", CORE, EDGE),
        ((60, 245, 1180, 390), "Application", APP, "#2f7d32"),
        ((60, 410, 1180, 540), "Ports", PORT, "#a36b00"),
        ((60, 560, 1180, 700), "Adapters", ADAPTER, "#6a3d9a"),
    ]
    for band in bands:
        _band(draw, band[0], band[1], band[2], band[3])

    boxes = [
        ((100, 145, 430, 210), "cli/main.py\nargparse + exit codes", CORE, EDGE),
        ((450, 145, 780, 210), "cli/repl.py\ncommands + persistence", CORE, EDGE),
        ((800, 145, 1140, 210), "cli/composition.py\ntools + KB + MCP wiring", CORE, EDGE),
        ((100, 285, 340, 365), "Agent facade\n184 lines", APP, "#2f7d32"),
        ((360, 285, 600, 365), "run_turn + context\nReAct + policy", APP, "#2f7d32"),
        ((620, 285, 860, 365), "tool_executor + mcp_tools\nexecution + bridge", APP, "#2f7d32"),
        ((880, 285, 1120, 365), "rag/knowledge\ningest + query", APP, "#2f7d32"),
        ((100, 450, 430, 515), "RuntimeStore\nProtocol", PORT, "#a36b00"),
        ((450, 450, 780, 515), "LLMClient\nProtocol", PORT, "#a36b00"),
        ((800, 450, 1140, 515), "MCPTransport\nProtocol", PORT, "#a36b00"),
        ((80, 600, 320, 675), "adapters/memory\nMySQL / SQLite", ADAPTER, "#6a3d9a"),
        ((340, 600, 580, 675), "adapters/llm\nOpenAI-compatible", ADAPTER, "#6a3d9a"),
        ((600, 600, 840, 675), "adapters/mcp\nclient + server", ADAPTER, "#6a3d9a"),
        ((860, 600, 1100, 675), "adapters/knowledge\nMySQL ngram / Chroma", ADAPTER, "#6a3d9a"),
    ]
    for box in boxes:
        _box(draw, box[0], box[1], box[2], box[3])

    external = [
        ((1260, 140, 1720, 225), "MySQL 8\nsessions · messages · documents", EXTERNAL, "#9ca3af"),
        ((1260, 295, 1720, 380), "Chroma (optional)\nvector index", EXTERNAL, "#9ca3af"),
        ((1260, 450, 1720, 535), "DeepSeek / OpenAI-compatible\nLLM endpoint", EXTERNAL, "#9ca3af"),
        ((1260, 605, 1720, 690), "External MCP servers\nstdio + profiles", EXTERNAL, "#9ca3af"),
    ]
    for box in external:
        _box(draw, box[0], box[1], box[2], box[3])

    _arrow(draw, (620, 225), (620, 245))
    for x in (220, 480, 740, 1000):
        _arrow(draw, (x, 390), (x, 410))
    _arrow(draw, (620, 540), (620, 560))

    _arrow(draw, (320, 475), (340, 610), dashed=True)
    _arrow(draw, (580, 475), (460, 600), dashed=True)
    _arrow(draw, (840, 475), (720, 600), dashed=True)
    _arrow(draw, (1180, 630), (1260, 180))
    _arrow(draw, (1180, 630), (1260, 335))
    _arrow(draw, (1180, 630), (1260, 490))
    _arrow(draw, (1180, 630), (1260, 645))

    draw.text(
        (60, 730),
        "A7: Agent is a 184-line facade | application depends on ports, not adapters | "
        "Legacy import shims stay until v0.4.0 | No DI container, no async rewrite",
        fill=INK,
        font=_font(19),
    )
    output = Path(__file__).with_name("architecture.png")
    image.save(output, "PNG", optimize=True)
    print(output)


if __name__ == "__main__":
    main()
