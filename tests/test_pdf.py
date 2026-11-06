import re
import zipfile, io

import pymupdf
import pytest

from slide2md import Cancelled, Options, convert
from slide2md.convert import build_zip, detect_kind
from slide2md.markdown import render_document
from slide2md.pdf_reader import page_text

FONT = pymupdf.Font("cjk")


def _doc_page(doc):
    page = doc.new_page(width=960, height=540)
    page.insert_font(fontname="kr", fontbuffer=FONT.buffer)
    return page


def test_sample_pdf_structure_without_ocr(sample_pdf, tmp_path, no_ocr):
    res = convert(sample_pdf, tmp_path, Options(ocr=True))
    assert res.kind == "pdf" and len(res.pages) == 5
    assert any("rapidocr" in w for w in res.warnings)
    p1, p2, p3, p4, p5 = res.pages

    assert p1.title == "Slide to Markdown"
    assert p1.blocks == ["PDF·PPTX 슬라이드를 페이지별 Markdown으로", "직접 만든 샘플 문서"]

    assert p2.title == "이 도구가 하는 일"
    lst = p2.blocks[0].splitlines()
    assert lst[0] == "- 페이지마다 텍스트를 뽑아 Markdown으로 정리합니다"
    assert lst[1] == "  - 큰 글자는 제목, 글머리표는 목록으로 바꿉니다"
    assert len(lst) == 5
    assert "공백 문자가 빠진 PDF도 띄어쓰기를 복원합니다" in p2.blocks  # 공백 문자 없이 찍힌 줄
    assert not any(b.strip() == "2" for b in p2.blocks)                # 쪽 번호는 뺌

    assert p3.title == "지원 형식"
    table = p3.blocks[0].splitlines()
    assert table[0] == "| 형식 | 본문 텍스트 | 그림 처리 |"
    assert table[-1] == "| 스캔 PDF | 없음 | 페이지 전체 OCR |"
    assert len(p3.blocks) == 1                                         # 표 안 글자가 본문에 또 나오지 않음

    # OCR이 없으면 큰 그림이 있는 페이지는 그림 위주, 도식 페이지도 그림 위주
    assert (p4.source, p4.reason) == ("image", "그림 26%")
    assert p5.source == "image" and p5.reason == "도형·도식"
    assert p5.images == ["p005.png"] and (tmp_path / "images" / "p005.png").stat().st_size > 1000
    assert res.counts() == {"text": 3, "ocr": 0, "image": 2}


def test_sample_pdf_with_ocr(sample_pdf, tmp_path, fake_ocr):
    res = convert(sample_pdf, tmp_path, Options())
    p4 = res.pages[3]
    assert fake_ocr.calls == 1                       # 그림 영역은 4쪽에 하나뿐
    assert p4.source == "ocr" and p4.ocr_chars == 100 and p4.images == []
    md = render_document(res)
    assert "**그림 속 글자 (OCR, 잡음이 있을 수 있음)**\n\n```text\n그림 속 글자" in md


def test_weak_ocr_marks_figure_page_as_image(sample_pdf, tmp_path, fake_ocr):
    fake_ocr.text = "흐릿함"
    res = convert(sample_pdf, tmp_path, Options())
    p4 = res.pages[3]
    assert p4.source == "image" and p4.reason.startswith("OCR 빈약 (3자") and p4.images == ["p004.png"]


def test_markdown_document_and_zip(sample_pdf, tmp_path, no_ocr):
    res = convert(sample_pdf, tmp_path, Options(ocr=False))
    md = render_document(res)
    assert md.startswith("# sample\n\n- 원본: sample.pdf (5쪽)\n- 페이지 구성: 텍스트 3 · 그림 위주 2\n")
    assert [l for l in md.splitlines() if l.startswith("## ")] == [
        "## 1쪽 · Slide to Markdown", "## 2쪽 · 이 도구가 하는 일", "## 3쪽 · 지원 형식", "## 4쪽 · 그림 속 글자", "## 5쪽 · 변환 흐름"]
    assert "![" not in md and "ZIP으로 받으면" in md
    assert "![5쪽 이미지](images/p005.png)" in render_document(res, with_images=True)

    z = zipfile.ZipFile(io.BytesIO(build_zip(res, tmp_path / "images")))
    names = set(z.namelist())
    assert {"sample.md", "pages/001.md", "pages/005.md", "images/p004.png", "images/p005.png"} <= names
    assert "](../images/p005.png)" in z.read("pages/005.md").decode()


def test_spacing_restored_from_char_gaps(tmp_path):
    doc = pymupdf.open()
    page = _doc_page(doc)
    x = 50
    for w in ["띄어쓰기가", "없는", "줄"]:
        page.insert_text((x, 100), w, fontname="kr", fontsize=20)
        x += FONT.text_length(w, 20) + 6
    page.insert_text((50, 160), "붙어있는글자", fontname="kr", fontsize=20)
    assert page_text(page) == "띄어쓰기가 없는 줄\n붙어있는글자"


def test_repeated_footer_removed(tmp_path, no_ocr):
    doc = pymupdf.open()
    for i in range(4):
        page = _doc_page(doc)
        page.insert_text((60, 80), f"제목 {i + 1}", fontname="kr", fontsize=30)
        page.insert_text((60, 160), f"본문 내용 {i + 1}", fontname="kr", fontsize=18)
        page.insert_text((60, 525), "© 샘플 단체 · 내부 자료", fontname="kr", fontsize=10)
        page.insert_text((880, 525), f"{i + 1} / 4", fontname="kr", fontsize=10)
    path = tmp_path / "footer.pdf"
    doc.save(str(path))
    res = convert(path, tmp_path / "out", Options(ocr=False))
    for i, p in enumerate(res.pages, 1):
        assert p.title == f"제목 {i}"
        assert p.blocks == [f"본문 내용 {i}"]


def test_text_only_page_with_few_chars_and_drawings_is_image(tmp_path, no_ocr):
    doc = pymupdf.open()
    _doc_page(doc).insert_text((60, 80), "보통 페이지", fontname="kr", fontsize=20)
    _doc_page(doc).insert_text((60, 80), "보통 페이지 둘", fontname="kr", fontsize=20)
    p = _doc_page(doc)
    p.draw_circle((480, 270), 120, color=(0, 0, 0))
    p.insert_text((440, 270), "원", fontname="kr", fontsize=20)
    path = tmp_path / "shape.pdf"
    doc.save(str(path))
    res = convert(path, tmp_path / "out", Options(ocr=False))
    assert [p.source for p in res.pages] == ["text", "text", "image"]
    assert res.pages[2].reason == "텍스트 거의 없음"


def test_progress_and_cancel(sample_pdf, tmp_path, no_ocr):
    seen = []
    convert(sample_pdf, tmp_path, Options(ocr=False), progress=lambda f, m: seen.append(f))
    assert seen[-1] == 1.0 and all(0 <= f <= 1 for f in seen) and seen == sorted(seen)
    with pytest.raises(Cancelled):
        convert(sample_pdf, tmp_path / "c", Options(ocr=False), cancel=lambda: True)


def test_detect_kind_rejects_wrong_files(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"not a pdf at all")
    with pytest.raises(ValueError, match="PDF 파일이 아닙니다"):
        detect_kind(fake)
    old = tmp_path / "old.pptx"
    old.write_bytes(b"\xd0\xcf\x11\xe0 old binary ppt")
    with pytest.raises(ValueError, match=".ppt 형식"):
        detect_kind(old)
    with pytest.raises(ValueError, match="지원하지 않는 형식"):
        detect_kind(fake, "notes.docx")


def test_encrypted_pdf_is_rejected(tmp_path):
    doc = pymupdf.open()
    _doc_page(doc).insert_text((60, 80), "비밀", fontname="kr", fontsize=20)
    path = tmp_path / "locked.pdf"
    doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="owner")
    with pytest.raises(ValueError, match="암호"):
        convert(path, tmp_path / "out", Options(ocr=False))


def test_sample_has_no_personal_paths(sample_pdf, sample_pptx):
    for f in (sample_pdf, sample_pptx):
        data = f.read_bytes()
        assert not re.search(rb"[A-Za-z]:\\\\?Users|/home/|/Users/", data)
