"""A small, dependency-free PDF writer for text reports.

**Why this exists rather than a library.** DECISION-4 in docs/PROJECT_CONTEXT.md — which PDF
engine to use — is still open, and §14 of that document gates reports on it. WeasyPrint
needs native GTK/Pango and is recorded as RISK-6 precisely because it tends to block PDF
generation outright on a Windows host; ReportLab would mean adding a dependency to a shared
``pyproject.toml`` and settling an open product question unilaterally.

So this module writes the PDF itself. A text-only report needs no library: PDF is a
text-based container, and the base-14 fonts (Helvetica here) are guaranteed present in every
reader, so nothing has to be embedded. The reporting brief asks for "simple and reliable"
and explicitly not for elaborate visual design, which is exactly the shape this fits.

It deliberately does **not** grow into a layout engine. There are pages, headings, paragraphs
wrapped to a measured width, and tables with fixed columns. If the project later wants charts
or styled output, DECISION-4 gets made and :func:`render` is replaced — the exporter
interface above it does not change, because it only ever hands over a
:class:`~app.modules.reports.model.Report`.

The output is PDF 1.4: a catalogue, a page tree, two base-14 fonts, one content stream per
page, an xref table and a trailer. It opens in any reader and the text is selectable and
searchable, which is what makes a report useful.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

PAGE_WIDTH = 595  # A4 at 72 dpi
PAGE_HEIGHT = 842
MARGIN = 48
LINE_HEIGHT = 13
BODY_SIZE = 9
HEADING_SIZE = 13
TITLE_SIZE = 17

FONT_REGULAR = "F1"
FONT_BOLD = "F2"

_TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN

# Helvetica is not monospaced; 0.5 em is a safe average for wrapping prose and sizing
# columns. Slightly conservative, so a line is never clipped by the page edge.
_AVERAGE_GLYPH = 0.5

_SUBSTITUTIONS = {
    "—": "-",
    "–": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    " ": " ",
    "≥": ">=",
    "≤": "<=",
    "→": "->",
}


def _ascii(value: str) -> str:
    """Fold the typography we use into characters a base-14 font certainly has.

    The alternative is embedding a font, which would make a 3 KB report a 300 KB one to
    render an em-dash. The substitutions are lossless in meaning.
    """
    for source, target in _SUBSTITUTIONS.items():
        value = value.replace(source, target)
    return value.encode("latin-1", "replace").decode("latin-1")


def _escape(value: str) -> str:
    """Escape the three characters that are syntax inside a PDF string literal."""
    return _ascii(value).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def wrap(text: str, size: float = BODY_SIZE, width: float = _TEXT_WIDTH) -> list[str]:
    """Break a paragraph into lines that fit the measured width.

    A word longer than a line — a long identifier, say — is broken rather than allowed to
    run off the page.
    """
    limit = max(int(width / (size * _AVERAGE_GLYPH)), 8)
    lines: list[str] = []
    for paragraph in _ascii(text).split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                lines.append(current)
            while len(word) > limit:
                lines.append(word[: limit - 1] + "-")
                word = word[limit - 1 :]
            current = word
        lines.append(current)
    return lines or [""]


class _Line:
    """One positioned run of text, ready to become a content-stream instruction."""

    __slots__ = ("text", "size", "bold", "indent")

    def __init__(self, text: str, *, size: float = BODY_SIZE, bold: bool = False, indent: int = 0):
        self.text = text
        self.size = size
        self.bold = bold
        self.indent = indent


class Document:
    """Lines accumulated into pages, then serialised."""

    def __init__(self) -> None:
        self._pages: list[list[_Line]] = [[]]
        self._used = 0.0

    @property
    def _page(self) -> list[_Line]:
        return self._pages[-1]

    def _room_for(self, height: float) -> None:
        if self._used + height > PAGE_HEIGHT - 2 * MARGIN:
            self._pages.append([])
            self._used = 0.0

    def line(
        self,
        text: str = "",
        *,
        size: float = BODY_SIZE,
        bold: bool = False,
        indent: int = 0,
    ) -> None:
        height = size + 4
        self._room_for(height)
        self._page.append(_Line(text, size=size, bold=bold, indent=indent))
        self._used += height

    def blank(self, height: float = LINE_HEIGHT * 0.6) -> None:
        self._room_for(height)
        self._page.append(_Line("", size=height - 4))
        self._used += height

    def paragraph(self, text: str, *, indent: int = 0, size: float = BODY_SIZE) -> None:
        for wrapped in wrap(text, size=size, width=_TEXT_WIDTH - indent):
            self.line(wrapped, size=size, indent=indent)

    def heading(self, text: str, *, size: float = HEADING_SIZE) -> None:
        self.blank()
        self.line(text, size=size, bold=True)

    def table(self, headers: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
        """A fixed-column grid, sized to the widest cell and clipped to the page.

        Columns share the text width in proportion to what they hold, so a long explanation
        does not squeeze a register number into two characters.
        """
        materialised = [list(row) for row in rows]
        widths = _column_widths(headers, materialised)
        self.line(_row(headers, widths), bold=True)
        self.line("-" * min(sum(widths) + len(widths), 110))
        for row in materialised:
            for wrapped in _wrap_row(row, widths):
                self.line(wrapped)
        if not materialised:
            self.line("(no rows)")

    def pages(self) -> list[list[_Line]]:
        return [page for page in self._pages if page] or [[]]


def _column_widths(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[int]:
    longest = [len(str(header)) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            longest[index] = max(longest[index], len(str(value)))
    budget = max(int(_TEXT_WIDTH / (BODY_SIZE * _AVERAGE_GLYPH)), 40)
    total = sum(longest) + len(longest)
    if total <= budget:
        return longest
    # Share the shortfall in proportion, never dropping below something readable.
    scaled = [max(int(width * budget / total), 6) for width in longest]
    return scaled


def _row(values: Sequence[str], widths: Sequence[int]) -> str:
    return " ".join(
        str(value)[:width].ljust(width) for value, width in zip(values, widths, strict=True)
    )


def _wrap_row(values: Sequence[str], widths: Sequence[int]) -> list[str]:
    """One row across as many lines as its longest cell needs."""
    stacks = [
        wrap(str(value), width=width * BODY_SIZE * _AVERAGE_GLYPH)
        if len(str(value)) > width
        else [str(value)]
        for value, width in zip(values, widths, strict=True)
    ]
    depth = max(len(stack) for stack in stacks) if stacks else 1
    lines = []
    for level in range(depth):
        lines.append(_row([stack[level] if level < len(stack) else "" for stack in stacks], widths))
    return lines


def _content_stream(lines: Sequence[_Line]) -> bytes:
    """One page's text, as PDF drawing instructions."""
    parts = ["BT"]
    cursor = PAGE_HEIGHT - MARGIN
    for line in lines:
        cursor -= line.size + 4
        if not line.text:
            continue
        font = FONT_BOLD if line.bold else FONT_REGULAR
        parts.append(f"/{font} {line.size:g} Tf")
        parts.append(f"1 0 0 1 {MARGIN + line.indent} {cursor:g} Tm")
        parts.append(f"({_escape(line.text)}) Tj")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def render(build: Document) -> bytes:
    """Serialise the document as a PDF 1.4 file."""
    pages = build.pages()
    page_count = len(pages)

    # 1 catalogue, 2 page tree, 3/4 fonts, then a page and a stream for each page.
    page_ids = [5 + 2 * index for index in range(page_count)]
    stream_ids = [6 + 2 * index for index in range(page_count)]

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Count {count} /Kids [{kids}] >>".format(
                count=page_count, kids=" ".join(f"{pid} 0 R" for pid in page_ids)
            ).encode("latin-1")
        ),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >>",
    }

    for index, lines in enumerate(pages):
        stream = _content_stream(lines)
        objects[page_ids[index]] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /{FONT_REGULAR} 3 0 R /{FONT_BOLD} 4 0 R >> >> "
            f"/Contents {stream_ids[index]} 0 R >>"
        ).encode("latin-1")
        objects[stream_ids[index]] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode("latin-1") + objects[number] + b"\nendobj\n"

    xref_at = len(out)
    highest = max(objects) + 1
    out += f"xref\n0 {highest}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for number in range(1, highest):
        if number in offsets:
            out += f"{offsets[number]:010d} 00000 n \n".encode("latin-1")
        else:  # a gap in the numbering would be a bug, but the table must stay well-formed
            out += b"0000000000 65535 f \n"
    out += (f"trailer\n<< /Size {highest} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n").encode(
        "latin-1"
    )
    return bytes(out)
