"""페이지 정보 → Markdown 문서 (전체 한 파일 / 페이지별 파일)."""
from pathlib import Path

from .model import SOURCE_LABEL
from .text import escape_md

UNIT = {"pdf": "쪽", "pptx": "슬라이드"}


def page_label(p, kind):
    return f"{p.number}쪽" if kind == "pdf" else f"슬라이드 {p.number}"


def page_heading(p, kind):
    return f"## {page_label(p, kind)}" + (f" · {escape_md(p.title)}" if p.title else "")


def render_page(p, kind, with_images=False, image_prefix="images/"):
    """with_images: 그림 위주 페이지에 이미지 링크를 넣음 (ZIP·미리보기용)."""
    out = [page_heading(p, kind), ""]
    if p.source == "image":
        note = f"> 그림 위주 페이지 — {p.reason}."
        note += " 아래 이미지를 함께 확인하세요." if with_images and p.images else \
            (" 원본 이미지는 ZIP으로 받으면 들어 있습니다." if p.images else "")
        out += [note, ""]
        if with_images:
            for name in p.images:
                out += [f"![{page_label(p, kind)} 이미지]({image_prefix}{name})", ""]
    for b in p.blocks:
        out += [b, ""]
    if not p.blocks and not p.ocr_text and p.source != "image":
        out += ["*(텍스트 없음)*", ""]
    if p.ocr_text:
        fence = "~~~" if "```" in p.ocr_text else "```"
        out += ["**그림 속 글자 (OCR, 잡음이 있을 수 있음)**", "", f"{fence}text", p.ocr_text.strip(), fence, ""]
    if p.notes:
        out += ["\n".join(["> **발표자 노트**", ">"] + [f"> {escape_md(l)}" if l else ">" for l in p.notes.splitlines()]), ""]
    return "\n".join(out).rstrip() + "\n"


def summary_line(result):
    c = result.counts()
    return " · ".join(f"{SOURCE_LABEL[k]} {c[k]}" for k in ("text", "ocr", "image") if c[k]) or "페이지 없음"


def render_document(result, with_images=False, image_prefix="images/"):
    name = Path(result.filename).stem
    head = [f"# {escape_md(name)}", "",
            f"- 원본: {escape_md(result.filename)} ({len(result.pages)}{UNIT[result.kind]})",
            f"- 페이지 구성: {summary_line(result)}"]
    head += [f"- 참고: {escape_md(w)}" for w in result.warnings]
    parts = ["\n".join(head) + "\n"]
    parts += [render_page(p, result.kind, with_images, image_prefix) for p in result.pages]
    return "\n".join(parts)
