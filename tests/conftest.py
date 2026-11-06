import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SAMPLES))


@pytest.fixture(scope="session")
def sample_pdf():
    return SAMPLES / "sample.pdf"


@pytest.fixture(scope="session")
def sample_pptx():
    return SAMPLES / "sample.pptx"


class FakeOcr:
    """실제 모델 없이 OCR 결과를 흉내 낸다. 호출된 이미지 수를 센다."""

    def __init__(self, text="그림 속 글자 " * 20, score=0.95):
        self.text, self.score, self.calls = text, score, 0

    def read(self, image, lang="korean"):
        self.calls += 1
        chars = len("".join(self.text.split()))
        return {"text": self.text.strip(), "chars": chars, "score": self.score if chars else 0.0}


@pytest.fixture
def fake_ocr(monkeypatch):
    from slide2md import ocr
    fake = FakeOcr()
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "engine", lambda lang="korean": None)
    monkeypatch.setattr(ocr, "read", fake.read)
    return fake


@pytest.fixture
def no_ocr(monkeypatch):
    from slide2md import ocr
    monkeypatch.setattr(ocr, "available", lambda: False)
