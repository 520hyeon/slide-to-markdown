"""PPTX → 슬라이드별 제목·문단·목록·표·차트·노트, 슬라이드 속 그림 OCR.

PPTX는 슬라이드 전체를 그림으로 그릴 수 없으므로 (lecture_transcriber/tools/pdf_pages.py와 같은 방식)
슬라이드 속 그림 파일을 OCR하고, 그림 위주 슬라이드는 그림 파일을 꺼내 둔다.
"""
import hashlib, re

from . import text as T
from .model import Cancelled, Page, judge
from .ocr import to_png

_NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _shapes(shapes):
    """읽는 순서(위→아래, 왼쪽→오른쪽)로 도형을 펼친다. 그룹 안도 같은 순서로."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    for sh in sorted(shapes, key=lambda s: ((s.top or 0), (s.left or 0))):
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _shapes(sh.shapes)
        else:
            yield sh


def _placeholder_type(sh):
    if not sh.is_placeholder:
        return None
    try:
        return sh.placeholder_format.type
    except Exception:
        return None


def _bullet_kind(paragraph, default):
    """문단 속성에 글머리표 지정이 있으면 따르고, 없으면 default ("bullet"|"number"|None)."""
    ppr = paragraph._p.find(f"{_NS_A}pPr")
    if ppr is not None:
        if ppr.find(f"{_NS_A}buNone") is not None:
            return None
        if ppr.find(f"{_NS_A}buAutoNum") is not None:
            return "number"
        if ppr.find(f"{_NS_A}buChar") is not None or ppr.find(f"{_NS_A}buBlip") is not None:
            return "bullet"
    return default


def _text_blocks(sh, body):
    """텍스트 상자 → Markdown 블록. 본문 자리표시자(body=True)는 글머리표 목록으로 본다."""
    out, items = [], []
    for para in sh.text_frame.paragraphs:
        txt = T.clean(para.text)
        if not txt:
            continue
        kind = _bullet_kind(para, "bullet" if body else ("bullet" if para.level > 0 else None))
        if kind:
            items.append((para.level, T.split_bullet(txt)[1].strip() or txt, kind == "number"))
        else:
            if items:
                out.append(T.md_list(items))
                items = []
            out.append(T.escape_md(txt))
    if items:
        out.append(T.md_list(items))
    return out


def _table_rows(tbl):
    return [[c.text for c in row.cells] for row in tbl.rows]


def _chart_rows(chart):
    plot = chart.plots[0]
    cats = [str(c) for c in plot.categories]
    series = list(plot.series)
    rows = [[""] + [s.name or f"계열 {k + 1}" for k, s in enumerate(series)]]
    for j, cat in enumerate(cats):
        rows.append([cat] + [_num(s.values[j]) if j < len(s.values) else "" for s in series])
    return rows


def _num(v):
    if v is None:
        return ""
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def read_pptx(path, opt, images_dir, progress, cancel, ocr_read):
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
    titles = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.VERTICAL_TITLE}
    bodies = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.VERTICAL_BODY,
              PP_PLACEHOLDER.VERTICAL_OBJECT}
    skip = {PP_PLACEHOLDER.SLIDE_NUMBER, PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.DATE}

    prs = Presentation(path)
    area = (prs.slide_width * prs.slide_height) or 1
    slides = list(prs.slides)
    n = len(slides)
    use_ocr = opt.ocr and ocr_read is not None
    for i, slide in enumerate(slides, 1):
        if cancel():
            raise Cancelled()
        title, blocks, plain, pics = "", [], [], []
        for sh in _shapes(slide.shapes):
            ph = _placeholder_type(sh)
            if ph in skip:
                continue
            if sh.has_text_frame and sh.text_frame.text.strip():
                if ph in titles and not title:
                    title = T.clean(sh.text_frame.text.replace("\n", " "))
                    continue
                b = _text_blocks(sh, ph in bodies)
                blocks += b
                plain.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                rows = _table_rows(sh.table)
                if md := T.md_table(rows):
                    blocks.append(md)
                    plain += [" ".join(r) for r in rows]
            if getattr(sh, "has_chart", False) and sh.has_chart:
                try:
                    ch = sh.chart
                    name = T.clean(ch.chart_title.text_frame.text) if ch.has_title else ""
                    md = T.md_table(_chart_rows(ch))
                    blocks.append(f"**차트{': ' + T.escape_md(name) if name else ''}**" + (f"\n\n{md}" if md else ""))
                    plain.append(name)
                except Exception:
                    blocks.append("**차트** (데이터를 읽지 못함)")
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE or (ph is not None and hasattr(sh, "image")):
                try:
                    img = sh.image
                except Exception:
                    continue
                pics.append((img, (sh.width or 0) * (sh.height or 0) / area))
        notes = ""
        if slide.has_notes_slide:
            notes = T.clean(slide.notes_slide.notes_text_frame.text if slide.notes_slide.notes_text_frame else "")
        text = "\n".join([title] + plain).strip()
        p = Page(number=i, title=title, blocks=blocks, text=T.clean(text), notes=notes,
                 chars=len(re.sub(r"\s+", "", text)),
                 image_cover=round(min(sum(c for _, c in pics), 1.0), 2))

        big = [(img, c) for img, c in pics if c >= opt.ocr_min_region]
        if big and use_ocr:
            progress((i - 1) / n, f"그림 속 글자 OCR {i}/{n}쪽")
            res = []
            for img, c in big:
                if cancel():
                    raise Cancelled()
                png = to_png(img.blob, opt.render_long_side)
                res.append((c, ocr_read(png) if png else {"text": "", "chars": 0, "score": 0.0}))
            judge(p, opt, res)
        elif p.image_cover >= opt.figure_min_cover:
            p.source, p.reason = "image", f"그림 {round(p.image_cover * 100)}%"
        if p.source != "image" and pics and p.chars < 25 and not p.ocr_chars:
            p.source, p.reason = "image", "텍스트 거의 없음"
        if p.source == "image":
            seen = set()
            for img, _ in pics:
                digest = hashlib.sha1(img.blob).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                png = to_png(img.blob, 4096)
                k = len(p.images) + 1
                name = f"p{i:03d}_{k}.png" if png else f"p{i:03d}_{k}.{img.ext}"
                (images_dir / name).write_bytes(png or img.blob)
                p.images.append(name)
        yield p
        progress(i / n, f"슬라이드 정리 중 {i}/{n}")
