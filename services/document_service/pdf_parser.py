import re
from pathlib import Path

from pypdf import PdfReader


class PdfExtractionError(Exception):
    pass


def clean_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(path: Path) -> tuple[int, list[tuple[int, str]]]:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise PdfExtractionError("The file could not be read as a PDF.") from exc

    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise PdfExtractionError("Password-protected PDFs are not supported.")
        except PdfExtractionError:
            raise
        except Exception as exc:
            raise PdfExtractionError("Password-protected PDFs are not supported.") from exc

    try:
        page_count = len(reader.pages)
    except Exception as exc:
        raise PdfExtractionError("The file could not be read as a PDF.") from exc

    pages: list[tuple[int, str]] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = clean_text(page.extract_text() or "")
        except Exception:
            text = ""
        if text:
            pages.append((number, text))
    return page_count, pages
