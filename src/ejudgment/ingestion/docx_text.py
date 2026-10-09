"""Plain text from a Word (.docx) file using only the standard library.

Body content is read in document order: paragraphs, and paragraphs inside table cells.
Tabs and line breaks are kept; paragraphs are separated by blank lines so the chunker sees
them as paragraph boundaries. A .docx has no fixed pages, so the result has no page mapping.
"""

import zipfile
from pathlib import Path
from xml.etree import ElementTree

# Bump when the conversion output changes, so converted pages are produced again.
DOCX_EXTRACTOR_VERSION = "docx-v1"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxError(Exception):
    """The file is not a readable Word document."""


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts).strip()


def docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError) as exc:
        raise DocxError(f"{path}: {exc}") from exc
    body = root.find(f"{_W}body")
    if body is None:
        return ""
    # iter() walks in document order, so table-cell paragraphs appear where the table is.
    paragraphs = [_paragraph_text(p) for p in body.iter(f"{_W}p")]
    return "\n\n".join(text for text in paragraphs if text)
