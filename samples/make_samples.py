"""샘플 PDF·PPTX 만들기 (실제 강의자료가 아니라 이 도구를 소개하는 직접 만든 예시).

    python samples/make_samples.py          → samples/sample.pdf, samples/sample.pptx

PDF 페이지 구성 (16:9)
    1 표지            큰 제목 + 부제
    2 글머리표        2단계 목록, 공백 문자 없이 단어만 띄워 놓은 줄(띄어쓰기 복원 확인용), 쪽 번호
    3 표              선으로 그린 3열 표
    4 그림 속 글자    글자가 들어 있는 그림(래스터) → OCR
    5 도식            상자·화살표가 많은 흐름도 → 그림 위주 페이지
"""
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
W, H = 960, 540
FONT = pymupdf.Font("cjk")  # PyMuPDF 내장 Droid Sans Fallback (한글 포함)
INK, SUB, LINE, ACCENT = (0.12, 0.14, 0.18), (0.35, 0.38, 0.45), (0.55, 0.58, 0.65), (0.15, 0.39, 0.85)


def new_page(doc, n=None):
    page = doc.new_page(width=W, height=H)
    page.insert_font(fontname="kr", fontbuffer=FONT.buffer)
    if n:
        put(page, W - 50, H - 24, str(n), 11, SUB)
    return page


def put(page, x, y, text, size, color=INK):
    page.insert_text((x, y), text, fontname="kr", fontsize=size, color=color)


def put_words(page, x, y, words, size, color=INK):
    """공백 문자를 넣지 않고 단어마다 따로 찍는다 (한국어 슬라이드 PDF에서 흔한 모양)."""
    for w in words:
        put(page, x, y, w, size, color)
        x += FONT.text_length(w, size) + size * 0.32


def title(page, text):
    put(page, 60, 80, text, 32)
    page.draw_line((60, 98), (W - 60, 98), color=LINE, width=1)


def text_image(lines, size=30, width=900, height=420):
    """글자가 들어 있는 그림(PNG bytes). PDF 텍스트 레이어에는 이 글자가 없다."""
    tmp = pymupdf.open()
    p = tmp.new_page(width=width, height=height)
    p.insert_font(fontname="kr", fontbuffer=FONT.buffer)
    p.draw_rect(p.rect, color=None, fill=(0.97, 0.98, 1.0))
    p.draw_rect(pymupdf.Rect(8, 8, width - 8, height - 8), color=ACCENT, width=3)
    y = 40 + size
    for ln in lines:
        p.insert_text((40, y), ln, fontname="kr", fontsize=size, color=INK)
        y += size * 2.0
    return p.get_pixmap(dpi=110).tobytes("png")


OCR_LINES = ["그림 안에 들어 있는 글자입니다", "PDF 텍스트 레이어에는 없어서",
             "RapidOCR로 그림 영역을 잘라 읽습니다", "Text inside images is read too",
             "읽은 글자는 페이지 끝에 따로 붙습니다"]


def diagram(page, top=150):
    steps = ["업로드", "텍스트 추출", "그림 OCR", "판정", "Markdown"]
    bw, gap = 140, 45
    x = (W - (bw * len(steps) + gap * (len(steps) - 1))) / 2
    for k, s in enumerate(steps):
        r = pymupdf.Rect(x, top, x + bw, top + 70)
        page.draw_rect(r, color=ACCENT, fill=(0.92, 0.95, 1.0), width=1.5, radius=0.2)
        put(page, r.x0 + (bw - FONT.text_length(s, 16)) / 2, r.y0 + 42, s, 16)
        for d in range(3):  # 상자마다 작은 점 장식
            page.draw_circle((r.x0 + 18 + d * 12, r.y1 + 18), 3, color=LINE, fill=LINE)
        if k < len(steps) - 1:
            ax = r.x1 + 6
            page.draw_line((ax, top + 35), (ax + gap - 12, top + 35), color=SUB, width=1.5)
            page.draw_line((ax + gap - 20, top + 29), (ax + gap - 12, top + 35), color=SUB, width=1.5)
            page.draw_line((ax + gap - 20, top + 41), (ax + gap - 12, top + 35), color=SUB, width=1.5)
        x += bw + gap
    # 갈래: 판정 → 그림 위주 페이지 이미지
    jx = (W - (bw * 5 + gap * 4)) / 2 + 3 * (bw + gap) + bw / 2
    page.draw_line((jx, top + 110), (jx, top + 170), color=SUB, width=1.5, dashes="[4] 0")
    r = pymupdf.Rect(jx - 90, top + 170, jx + 90, top + 230)
    page.draw_rect(r, color=SUB, fill=(0.96, 0.96, 0.96), width=1, radius=0.2)
    put(page, r.x0 + 30, r.y0 + 36, "페이지 이미지", 15, SUB)


def make_pdf(path):
    doc = pymupdf.open()
    doc.set_metadata({"title": "Slide to Markdown 샘플", "author": "slide-to-markdown", "creator": "make_samples.py"})

    p = new_page(doc)
    put(p, 80, 250, "Slide to Markdown", 46)
    put(p, 82, 300, "PDF·PPTX 슬라이드를 페이지별 Markdown으로", 22, SUB)
    put(p, 82, 470, "직접 만든 샘플 문서", 13, SUB)

    p = new_page(doc, 2)
    title(p, "이 도구가 하는 일")
    y = 150
    for lvl, txt in [(0, "페이지마다 텍스트를 뽑아 Markdown으로 정리합니다"),
                     (1, "큰 글자는 제목, 글머리표는 목록으로 바꿉니다"),
                     (1, "선으로 그린 표는 Markdown 표가 됩니다"),
                     (0, "그림 속 글자는 OCR로 읽습니다"),
                     (0, "결과는 .md 파일이나 페이지별 파일이 든 ZIP으로 받습니다")]:
        x = 70 + lvl * 36
        put(p, x, y, "•" if lvl == 0 else "–", 20, ACCENT if lvl == 0 else SUB)
        put(p, x + 24, y, txt, 20 if lvl == 0 else 18, INK if lvl == 0 else SUB)
        y += 44
    put_words(p, 70, y + 30, ["공백", "문자가", "빠진", "PDF도", "띄어쓰기를", "복원합니다"], 18, SUB)

    p = new_page(doc, 3)
    title(p, "지원 형식")
    rows = [["형식", "본문 텍스트", "그림 처리"],
            ["PDF", "텍스트 레이어", "그림 영역을 잘라 OCR"],
            ["PPTX", "텍스트 상자·표·노트", "슬라이드 속 그림 OCR"],
            ["스캔 PDF", "없음", "페이지 전체 OCR"]]
    xs, y0, rh = [70, 250, 560, 890], 140, 52
    for r in range(len(rows) + 1):
        p.draw_line((xs[0], y0 + r * rh), (xs[-1], y0 + r * rh), color=LINE, width=1)
    for x in xs:
        p.draw_line((x, y0), (x, y0 + len(rows) * rh), color=LINE, width=1)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            put(p, xs[c] + 14, y0 + r * rh + 33, cell, 17, INK if r else ACCENT)

    p = new_page(doc, 4)
    title(p, "그림 속 글자")
    put(p, 70, 140, "아래는 글자를 그림으로 넣은 예시입니다.", 18, SUB)
    p.insert_image(pymupdf.Rect(70, 160, 610, 436), stream=text_image(OCR_LINES))

    p = new_page(doc, 5)
    title(p, "변환 흐름")
    diagram(p)

    doc.subset_fonts()
    doc.save(str(path), garbage=4, deflate=True)
    return path


def diagram_png():
    doc = pymupdf.open()
    p = new_page(doc)
    diagram(p, top=120)
    return p.get_pixmap(dpi=96).tobytes("png")


def make_pptx(path):
    import io
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    L = prs.slide_layouts

    s = prs.slides.add_slide(L[0])
    s.shapes.title.text = "Slide to Markdown 샘플"
    s.placeholders[1].text = "직접 만든 PPTX 예시"

    s = prs.slides.add_slide(L[1])
    s.shapes.title.text = "변환 규칙"
    tf = s.placeholders[1].text_frame
    tf.text = "제목 자리표시자는 페이지 제목이 됩니다"
    for lvl, txt in [(0, "본문 자리표시자는 글머리표 목록이 됩니다"), (1, "들여쓰기 단계도 유지합니다"),
                     (1, "표와 차트는 Markdown 표로 바꿉니다"), (0, "발표자 노트는 페이지 끝에 붙습니다")]:
        para = tf.add_paragraph()
        para.text, para.level = txt, lvl
    s.notes_slide.notes_text_frame.text = "발표자 노트 예시입니다.\n두 번째 줄도 들어갑니다."

    s = prs.slides.add_slide(L[5])
    s.shapes.title.text = "지원 형식"
    data = [["형식", "본문 텍스트", "그림 처리"], ["PDF", "텍스트 레이어", "그림 영역 OCR"],
            ["PPTX", "텍스트 상자·표·노트", "슬라이드 속 그림 OCR"]]
    tbl = s.shapes.add_table(3, 3, Inches(0.8), Inches(1.8), Inches(11.5), Inches(2)).table
    for r, row in enumerate(data):
        for c, v in enumerate(row):
            tbl.cell(r, c).text = v

    s = prs.slides.add_slide(L[5])
    s.shapes.title.text = "그림 속 글자"
    s.shapes.add_picture(io.BytesIO(text_image(OCR_LINES)), Inches(0.8), Inches(1.6), height=Inches(3.4))

    s = prs.slides.add_slide(L[5])
    s.shapes.title.text = "페이지 구성 예"
    cd = CategoryChartData()
    cd.categories = ["텍스트", "텍스트 + OCR", "그림 위주"]
    cd.add_series("페이지 수", (3, 1, 1))
    s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1.6), Inches(8), Inches(5), cd)

    s = prs.slides.add_slide(L[6])
    box = s.shapes.add_textbox(Inches(0.6), Inches(0.3), Inches(6), Inches(0.6))
    box.text_frame.text = "변환 흐름"
    box.text_frame.paragraphs[0].runs[0].font.size = Pt(20)
    s.shapes.add_picture(io.BytesIO(diagram_png()), Inches(0.4), Inches(1.0), width=Inches(12.5))

    prs.core_properties.title = "Slide to Markdown 샘플"
    prs.core_properties.author = "slide-to-markdown"
    prs.save(str(path))
    return path


if __name__ == "__main__":
    print(make_pdf(HERE / "sample.pdf"))
    print(make_pptx(HERE / "sample.pptx"))
