"""변환 옵션, 페이지 정보, 페이지 텍스트 출처 판정."""
from dataclasses import asdict, dataclass, field

SOURCE_LABEL = {"text": "텍스트", "ocr": "텍스트 + OCR", "image": "그림 위주"}


class Cancelled(Exception):
    """사용자가 변환을 취소함."""


@dataclass
class Options:
    ocr: bool = True                # 그림 영역을 OCR (RapidOCR가 설치돼 있어야 함)
    ocr_lang: str = "korean"        # korean(한국어+영어) | en
    render_long_side: int = 1280    # OCR·페이지 이미지 해상도: 긴 변(px)
    # 판정 기준 (lecture_transcriber의 기본값과 같음)
    ocr_min_region: float = 0.02    # 페이지 면적 대비 이 비율 이상인 그림만 OCR
    figure_min_cover: float = 0.12  # 그림이 이 비율 이상 덮으면 "그림 페이지"로 보고 OCR 결과를 판정
    ocr_min_chars: int = 80         # 그림 속 OCR 글자 수(공백 제외)가 이보다 적으면 그림 위주
    ocr_min_density: int = 300      # OCR 글자 수 ÷ 그림 면적 비율이 이보다 낮으면 그림 위주 (도식)
    ocr_min_score: float = 0.80     # OCR 평균 신뢰도가 이보다 낮으면 그림 위주


@dataclass
class Page:
    number: int
    title: str = ""
    blocks: list = field(default_factory=list)  # Markdown 블록 (문단, 목록, 표)
    text: str = ""                              # 본문 평문 (글자 수 계산, 미리보기 검색용)
    notes: str = ""                             # PPTX 발표자 노트
    chars: int = 0
    image_cover: float = 0.0                    # 그림이 페이지를 덮는 비율
    drawings: int = 0                           # 표 밖 도형 수 (PDF)
    ocr_text: str = ""
    ocr_chars: int = 0
    ocr_score: float = 0.0
    ocr_density: int = 0
    source: str = "text"                        # text | ocr | image
    reason: str = ""                            # 그림 위주로 본 이유
    images: list = field(default_factory=list)  # images/ 안의 파일 이름

    def summary(self):
        d = asdict(self)
        for k in ("blocks", "text", "ocr_text", "notes"):
            d.pop(k)
        d["source_label"] = SOURCE_LABEL[self.source]
        return d


@dataclass
class Result:
    filename: str
    kind: str                                   # pdf | pptx
    pages: list
    warnings: list = field(default_factory=list)

    def counts(self):
        c = {"text": 0, "ocr": 0, "image": 0}
        for p in self.pages:
            c[p.source] += 1
        return c


def judge(p, opt, regions):
    """regions: [(그림 면적 비율, {"text","chars","score"})] → p.source / reason / ocr_* 기록.

    그림이 페이지를 충분히 덮는데 OCR 결과가 빈약하면(글자가 적거나, 면적에 비해 성기거나, 신뢰도가 낮음)
    도식·사진 같은 그림 위주 페이지로 본다.
    """
    cover = sum(c for c, _ in regions)
    if not regions:
        p.source = "text"
        return
    chars = sum(r["chars"] for _, r in regions)
    score = round(sum(r["score"] * r["chars"] for _, r in regions) / chars, 3) if chars else 0.0
    dens = round(chars / cover) if cover else 0
    p.ocr_chars, p.ocr_score, p.ocr_density = chars, score, dens
    p.ocr_text = "\n".join(r["text"] for _, r in regions if r["text"])
    if cover >= opt.figure_min_cover:
        weak = []
        if chars < opt.ocr_min_chars:
            weak.append(f"{chars}자")
        if dens < opt.ocr_min_density:
            weak.append(f"밀도 {dens}")
        if chars and score < opt.ocr_min_score:
            weak.append(f"신뢰도 {score}")
        if weak:
            p.source, p.reason = "image", "OCR 빈약 (" + ", ".join(weak) + ")"
            return
    p.source = "ocr" if chars else "text"
