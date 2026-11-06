"""실제 RapidOCR로 샘플 그림을 읽는다. rapidocr가 없거나 모델을 받을 수 없으면 건너뛴다."""
import pytest

from slide2md import Options, convert, ocr

pytestmark = pytest.mark.skipif(not ocr.available(), reason="rapidocr 미설치")


@pytest.fixture(scope="module")
def engine_ready():
    try:
        ocr.engine("korean")
    except Exception as e:  # 첫 실행에 모델을 내려받지 못한 경우 등
        pytest.skip(f"OCR 엔진을 준비하지 못함: {e}")


def test_real_ocr_reads_text_inside_figure(sample_pdf, tmp_path, engine_ready):
    res = convert(sample_pdf, tmp_path, Options())
    p4 = res.pages[3]
    assert p4.source == "ocr", p4.reason
    for line in ("그림 안에 들어 있는 글자입니다", "RapidOCR로 그림 영역을 잘라 읽습니다", "Text inside images is read too"):
        assert line in p4.ocr_text
    assert p4.ocr_score >= 0.9


def test_real_ocr_on_korean_line_that_orientation_classifier_flips(engine_ready):
    """방향 분류기를 켜면 이 줄을 180° 뒤집어 읽어 엉뚱한 글자가 나왔다 (ocr.py 주석 참고)."""
    import make_samples as M
    r = ocr.read(M.text_image(["그림 안에 들어 있는 글자입니다"], height=160))
    assert r["text"] == "그림 안에 들어 있는 글자입니다" and r["score"] > 0.9
