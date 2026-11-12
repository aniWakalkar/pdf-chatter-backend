from dataclasses import dataclass

MIN_CHUNK_CHARS = 20
_SEPARATORS = ("\n\n", ". ", "? ", "! ", "\n", "; ", " ")


@dataclass
class Chunk:
    chunk_index: int
    page_number: int
    content: str


def split_text(text: str, size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    pieces: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            window = text[start:end]
            for separator in _SEPARATORS:
                index = window.rfind(separator)
                if index > size * 0.5:
                    end = start + index + len(separator)
                    break
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= length:
            break
        next_start = max(end - overlap, start + 1)
        boundary = text.find(" ", next_start, end)
        if boundary != -1:
            next_start = boundary + 1
        start = next_start
    return pieces


def chunk_pages(pages: list[tuple[int, str]], size: int, overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page_number, text in pages:
        for piece in split_text(text, size, overlap):
            if len(piece) >= MIN_CHUNK_CHARS:
                chunks.append(Chunk(chunk_index=len(chunks), page_number=page_number, content=piece))
    return chunks
