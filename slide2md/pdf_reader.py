"""PDF → 페이지별 제목·문단·목록·표, 그림 영역 OCR, 그림 위주 페이지 판정.

텍스트 추출과 그림 판정은 lecture_transcriber/tools/pdf_pages.py의 방식을 따른다.
- 글자 사이 간격으로 띄어쓰기를 복원한다 (한국어 슬라이드 PDF는 공백 문자가 빠져 있는 경우가 많음).
- 그림 영역을 잘라 OCR하고, 그림이 큰데 OCR 결과가 빈약하면 그림 위주 페이지로 보고 페이지 이미지를 만든다.
- 도형이 다른 페이지보다 훨씬 많거나(도식) 글자가 거의 없는 페이지도 그림 위주로 본다.
"""
import re, statistics
from collections import Counter

import pymupdf

from . import text as T
from .model import Cancelled, Page, judge

_FLAGS = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
_PAGE_NO = re.compile(r"^[\s\-–(]*\d{1,4}(\s*/\s*\d{1,4})?[\s\-–)]*$")
_NUMBERED = re.compile(r"^\s*(\d{1,2}[.)]|[①-⑳]|\(\d{1,2}\))\s*")


def join_chars(chars):
    """[(글자, bbox, 크기)] → 문자열. 글자 사이가 글자 크기의 15%보다 벌어져 있으면 공백을 넣는다."""
    out, prev = [], None
    for ch, bbox, size in chars:
        if prev is not None and ch != " " and prev[0] != " " and bbox[0] - prev[1][2] > size * 0.15:
            out.append(" ")
        out.append(ch)
        prev = (ch, bbox)
    return "".join(out)


class Line:
    __slots__ = ("chars", "raw", "text", "bbox", "size", "block")

    def __init__(self, chars, bbox, block):
        self.chars, self.bbox, self.block = chars, bbox, block
        self.raw = join_chars(chars)
        self.text = T.clean(self.raw)
        sizes = Counter(round(s, 1) for c, _, s in chars if c.strip())
        self.size = sizes.most_common(1)[0][0] if sizes else 10.0

    @property
    def center(self):
        return (self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2


def page_lines(page):
    lines = []
    for bi, b in enumerate(page.get_text("rawdict", flags=_FLAGS)["blocks"]):
        for l in b.get("lines", []):
            chars = [(c["c"], c["bbox"], s["size"]) for s in l["spans"] for c in s["chars"]]
            if chars and "".join(c for c, _, _ in chars).strip():
                lines.append(Line(chars, tuple(l["bbox"]), bi))
    return [l for l in lines if l.text or T.bullet_only(l.raw)]


def page_text(page):
    """띄어쓰기를 복원한 페이지 평문 (구조 없이)."""
    return "\n".join(l.text for l in page_lines(page) if l.text)


def _inside(pt, r, pad=1.0):
    return r[0] - pad <= pt[0] <= r[2] + pad and r[1] - pad <= pt[1] <= r[3] + pad


def find_tables(page):
    try:
        tabs = page.find_tables(use_layout=False).tables  # PyMuPDF 2.x: 선 기반 감지
    except TypeError:
        tabs = page.find_tables().tables
    except Exception:
        return []
    return [t for t in tabs if t.row_count >= 2 and t.col_count >= 2]


def table_rows(table, lines):
    """표 셀마다 그 안에 있는 글자를 모아 띄어쓰기를 복원한 문자열로."""
    cells = [(ri, ci, c) for ri, row in enumerate(table.rows) for ci, c in enumerate(row.cells) if c]
    grid = [[""] * len(row.cells) for row in table.rows]
    for ri, ci, box in cells:
        parts = []
        for l in lines:
            if not (l.bbox[2] >= box[0] and l.bbox[0] <= box[2] and l.bbox[3] >= box[1] and l.bbox[1] <= box[3]):
                continue
            chs = [c for c in l.chars if _inside(((c[1][0] + c[1][2]) / 2, (c[1][1] + c[1][3]) / 2), box, 0)]
            if chs:
                parts.append(T.clean(join_chars(chs)))
        grid[ri][ci] = " ".join(p for p in parts if p)
    return grid


def _weighted_median(pairs):
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0] if pairs else 0


def pick_title(lines, page_h, ref=None):
    """다른 글자보다 확실히 큰 글자를 제목으로 (위쪽에 있거나 훨씬 클 때). → (제목, 줄 번호 집합)

    ref: 본문 글자 크기를 잴 줄 (표 안 글자 포함). 없으면 lines.
    """
    ref = ref if ref is not None else lines
    if not lines or len(ref) < 2:
        return "", set()
    body = _weighted_median([(l.size, len(l.text)) for l in ref if l.text])
    top = max(l.size for l in lines)
    if not body or top < body * 1.2:
        return "", set()
    cand = sorted((i for i, l in enumerate(lines) if l.size >= top * 0.95 and l.text), key=lambda i: lines[i].bbox[1])
    if not cand:
        return "", set()
    first = lines[cand[0]]
    if first.bbox[1] > page_h * 0.4 and top < body * 1.4:
        return "", set()
    pick = [cand[0]]
    for i in cand[1:]:
        if lines[i].bbox[1] - lines[pick[-1]].bbox[3] < top * 0.8:
            pick.append(i)
        else:
            break
    title = " ".join(lines[i].text for i in pick)
    if len(title) > 150:
        return "", set()
    return title, set(pick)


def _cluster(xs, tol):
    out = []
    for x in sorted(xs):
        if not out or x - out[-1][-1] > tol:
            out.append([x])
        else:
            out[-1].append(x)
    return [sum(g) / len(g) for g in out]


def body_elements(lines, skip, body_size):
    """줄 → [{"kind": "li"|"p", "text", "level", "y"}]. 글머리표 단계는 글머리표의 x 위치로 정한다."""
    use = [(i, l) for i, l in enumerate(lines) if i not in skip]
    bxs = [l.bbox[0] for _, l in use if T.split_bullet(l.raw)[0] or T.bullet_only(l.raw)]
    levels = _cluster(bxs, body_size * 0.8)

    def level_of(x):
        return min(range(len(levels)), key=lambda k: abs(levels[k] - x)) if levels else 0

    block_right = {}
    for _, l in use:
        block_right[l.block] = max(block_right.get(l.block, 0), l.bbox[2])

    els, pending, prev = [], None, None
    for _, l in use:
        if T.bullet_only(l.raw):  # 글머리표가 글자와 따로 떨어진 줄로 나온 경우
            pending = l
            continue
        is_b, rest = T.split_bullet(l.raw)
        txt = T.clean(rest)
        if not txt:
            continue
        bx = l.bbox[0]
        if pending is not None and abs(pending.center[1] - l.center[1]) < l.size * 0.8:
            is_b, bx = True, pending.bbox[0]
        pending = None
        last = els[-1] if els else None
        near = (last is not None and prev is not None and last["block"] == l.block
                and l.bbox[1] - prev.bbox[3] < l.size * 0.8)
        wrapped = near and prev.bbox[2] >= block_right[l.block] - prev.size * 1.5
        if is_b:
            els.append({"kind": "li", "text": txt, "level": level_of(bx), "x": bx, "y": l.bbox[1], "block": l.block})
        elif near and last["kind"] == "li" and l.bbox[0] > last["x"] + l.size * 0.5 and not _NUMBERED.match(txt):
            last["text"] += " " + txt  # 글머리표 항목의 다음 줄
        elif near and wrapped and last["kind"] == "p" and abs(l.bbox[0] - last["x"]) < l.size \
                and not _NUMBERED.match(txt):
            last["text"] += " " + txt  # 줄바꿈된 문단
        else:
            els.append({"kind": "p", "text": txt, "level": 0, "x": l.bbox[0], "y": l.bbox[1], "block": l.block})
        prev = l
    return els


def render_blocks(els, tables):
    """요소와 표(y 위치 순)를 Markdown 블록으로."""
    tables = sorted(tables, key=lambda t: t[0])
    out, items = [], []

    def flush():
        if items:
            out.append(T.md_list(items))
            items.clear()

    for e in els:
        while tables and tables[0][0] < e["y"]:
            flush()
            out.append(tables.pop(0)[1])
        if e["kind"] == "li":
            items.append((e["level"], e["text"], False))
        else:
            flush()
            out.append(T.escape_md(e["text"]))
    flush()
    out += [md for _, md in tables]
    return [b for b in out if b]


def _band_key(l, page_h, body_size):
    """위·아래 가장자리의 본문 크기 이하 글이면 비교용 키 (숫자는 #으로). 제목처럼 큰 글자는 대상이 아님."""
    if (l.bbox[1] < page_h * 0.1 or l.bbox[3] > page_h * 0.9) and l.size <= body_size * 1.05:
        return re.sub(r"\d+", "#", l.text)
    return None


def read_pdf(path, opt, images_dir, progress, cancel, ocr_read):
    doc = pymupdf.open(path)
    if doc.needs_pass:
        raise ValueError("암호가 걸린 PDF는 열 수 없습니다.")
    n = len(doc)
    raw = []
    for i, page in enumerate(doc):
        if cancel():
            raise Cancelled()
        area = page.rect.width * page.rect.height or 1
        lines = page_lines(page)
        tables = find_tables(page) if page.get_cdrawings() else []
        tboxes = [tuple(t.bbox) for t in tables]
        drawings = sum(1 for d in page.get_cdrawings()
                       if not any(_inside((d["rect"][0], d["rect"][1]), b, 2) and _inside((d["rect"][2], d["rect"][3]), b, 2)
                                  for b in tboxes))
        boxes, seen = [], set()
        for b in page.get_image_info():
            r = pymupdf.Rect(b["bbox"]) & page.rect
            key = tuple(round(v) for v in r)
            if not r.is_empty and key not in seen:
                seen.add(key)
                boxes.append(r)
        cov = sum(b.get_area() for b in boxes) / area
        size = _weighted_median([(l.size, len(l.text)) for l in lines if l.text]) or 10
        raw.append({"lines": lines, "tables": tables, "drawings": drawings, "boxes": boxes, "size": size,
                    "cover": round(min(cov, 1.0), 2), "regions": [b for b in boxes if b.get_area() / area >= opt.ocr_min_region]})
        progress(0.1 * (i + 1) / n, f"페이지 읽는 중 {i + 1}/{n}")

    # 여러 페이지 위·아래 가장자리에 똑같이 반복되는 글(머리글·바닥글·쪽 번호)은 뺀다
    band = Counter()
    for i, r in enumerate(raw):
        h = doc[i].rect.height
        band.update({k for l in r["lines"] if (k := _band_key(l, h, r["size"]))})
    repeated = {k for k, c in band.items() if n >= 3 and c >= max(3, n * 0.5)}

    base_draw = statistics.median(r["drawings"] for r in raw) if raw else 0
    use_ocr = opt.ocr and ocr_read is not None
    units = n + sum(3 * len(r["regions"]) for r in raw) if use_ocr else n
    done = 0
    pages = []
    for i, r in enumerate(raw):
        page = doc[i]
        h = page.rect.height
        area = page.rect.width * h or 1
        lines = r["lines"]
        skip = set()
        for j, l in enumerate(lines):
            if _band_key(l, h, r["size"]) in repeated or (l.bbox[1] > h * 0.88 and _PAGE_NO.match(l.text)):
                skip.add(j)
        ref = [l for j, l in enumerate(lines) if j not in skip]
        tables = []
        for t in r["tables"]:
            tb = tuple(t.bbox)
            md = T.md_table(table_rows(t, lines))
            if md:
                tables.append((tb[1], md))
                skip |= {j for j, l in enumerate(lines) if _inside(l.center, tb)}
        title, tidx = pick_title([l for j, l in enumerate(lines) if j not in skip], h, ref)
        if tidx:
            rest = [j for j in range(len(lines)) if j not in skip]
            skip |= {rest[k] for k in tidx}
        body = [l for j, l in enumerate(lines) if j not in skip and l.text]
        body_size = _weighted_median([(l.size, len(l.text)) for l in body]) or 10
        els = body_elements(lines, skip, body_size)
        text = "\n".join([title] + [e["text"] for e in els] + [md for _, md in tables]).strip()
        p = Page(number=i + 1, title=title, blocks=render_blocks(els, tables), text=text,
                 chars=len(re.sub(r"\s+", "", text)), image_cover=r["cover"], drawings=r["drawings"])

        zoom = opt.render_long_side / max(page.rect.width, h)
        if r["regions"] and use_ocr:
            res = []
            for b in r["regions"]:
                if cancel():
                    raise Cancelled()
                progress(0.1 + 0.9 * done / units, f"그림 속 글자 OCR {i + 1}/{n}쪽")
                # 작은 그림은 키워서 읽는다: 영역 긴 변이 render_long_side가 되게 (페이지 배율의 1~3배)
                rz = min(max(zoom, opt.render_long_side / max(b.width, b.height, 1)), zoom * 3)
                png = page.get_pixmap(matrix=pymupdf.Matrix(rz, rz), clip=b).tobytes("png")
                res.append((b.get_area() / area, ocr_read(png)))
                done += 3
            judge(p, opt, res)
        elif p.image_cover >= opt.figure_min_cover:  # OCR을 쓰지 않을 때
            p.source, p.reason = "image", f"그림 {round(p.image_cover * 100)}%"
        if p.source != "image":
            if p.drawings > base_draw + 20:
                p.source, p.reason = "image", "도형·도식"
            elif p.chars < 25 and not p.ocr_chars and (p.image_cover > 0.02 or p.drawings > base_draw):
                p.source, p.reason = "image", "텍스트 거의 없음"
        if p.source == "image":
            name = f"p{p.number:03d}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).save(str(images_dir / name))
            p.images = [name]
        pages.append(p)
        done += 1
        progress(0.1 + 0.9 * done / units, f"페이지 정리 중 {i + 1}/{n}")
    return pages
