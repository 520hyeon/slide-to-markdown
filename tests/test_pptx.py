import io

from slide2md import Options, convert
from slide2md.markdown import render_document


def test_sample_pptx(sample_pptx, tmp_path, fake_ocr):
    res = convert(sample_pptx, tmp_path, Options())
    assert res.kind == "pptx" and len(res.pages) == 6
    s1, s2, s3, s4, s5, s6 = res.pages

    assert (s1.title, s1.blocks) == ("Slide to Markdown 샘플", ["직접 만든 PPTX 예시"])

    assert s2.title == "변환 규칙"
    assert s2.blocks[0].splitlines() == [
        "- 제목 자리표시자는 페이지 제목이 됩니다",
        "- 본문 자리표시자는 글머리표 목록이 됩니다",
        "  - 들여쓰기 단계도 유지합니다",
        "  - 표와 차트는 Markdown 표로 바꿉니다",
        "- 발표자 노트는 페이지 끝에 붙습니다",
    ]
    assert s2.notes == "발표자 노트 예시입니다.\n두 번째 줄도 들어갑니다."

    assert s3.blocks[0].splitlines()[0] == "| 형식 | 본문 텍스트 | 그림 처리 |"

    assert s4.source == "ocr" and fake_ocr.calls >= 1     # 글자 그림 → OCR
    assert s5.blocks[0].startswith("**차트**") and "| 텍스트 | 3 |" in s5.blocks[0]
    assert s6.blocks == ["변환 흐름"]

    md = render_document(res)
    assert "## 슬라이드 2 · 변환 규칙" in md
    assert "> **발표자 노트**\n>\n> 발표자 노트 예시입니다.\n> 두 번째 줄도 들어갑니다." in md


def test_pptx_picture_slide_without_ocr_exports_png(sample_pptx, tmp_path, no_ocr):
    res = convert(sample_pptx, tmp_path, Options())
    s6 = res.pages[5]
    assert s6.source == "image" and s6.images == ["p006_1.png"]
    assert (tmp_path / "images" / "p006_1.png").read_bytes()[:4] == b"\x89PNG"
    assert "![슬라이드 6 이미지](images/p006_1.png)" in render_document(res, with_images=True)


def test_pptx_text_box_bullets_and_numbering(tmp_path, no_ocr):
    from lxml import etree
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tf = s.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(3)).text_frame
    tf.text = "그냥 문단"
    for txt in ("첫 단계", "둘째 단계"):
        p = tf.add_paragraph()
        p.text = txt
        ppr = p._p.get_or_add_pPr()
        etree.SubElement(ppr, "{http://schemas.openxmlformats.org/drawingml/2006/main}buAutoNum", type="arabicPeriod")
    p = tf.add_paragraph()
    p.text, p.level = "들여쓴 문단", 1
    path = tmp_path / "boxes.pptx"
    prs.save(path)

    res = convert(path, tmp_path / "out", Options(ocr=False))
    assert res.pages[0].blocks == ["그냥 문단", "1. 첫 단계\n2. 둘째 단계\n   - 들여쓴 문단"]
