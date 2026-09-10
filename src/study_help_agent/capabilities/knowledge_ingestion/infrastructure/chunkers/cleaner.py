"""对已生成文本做保守清理，不破坏 Markdown 标题、列表和代码围栏。"""

import re


def clean_text(text: str) -> str:
    """统一换行、移除控制字符并压缩过多空行。"""

    value = text.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(char for char in value if char in "\n\t" or ord(char) >= 32)
    value = re.sub(r"[ \t]+\n", "\n", value)
    return re.sub(r"\n{4,}", "\n\n\n", value).strip()


def recursive_bound(text: str, *, max_characters: int, overlap: int) -> tuple[str, ...]:
    """优先按段落和行切分超长文本，最后才使用字符窗口。"""

    cleaned = clean_text(text)
    if not cleaned:
        return ()
    if len(cleaned) <= max_characters:
        return (cleaned,)
    for separator in ("\n\n", "\n", "。", "；", "，"):
        pieces = cleaned.split(separator)
        if len(pieces) < 2:
            continue
        chunks: list[str] = []
        current = ""
        for piece in pieces:
            candidate = piece if not current else f"{current}{separator}{piece}"
            if len(candidate) <= max_characters:
                current = candidate
                continue
            if current:
                chunks.extend(recursive_bound(current, max_characters=max_characters, overlap=overlap))
            current = piece
        if current:
            chunks.extend(recursive_bound(current, max_characters=max_characters, overlap=overlap))
        if chunks:
            return tuple(chunks)
    step = max(1, max_characters - overlap)
    return tuple(
        cleaned[start : start + max_characters]
        for start in range(0, len(cleaned), step)
        if cleaned[start : start + max_characters].strip()
    )
