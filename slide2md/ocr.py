"""그림 속 글자 OCR (RapidOCR, 무료·로컬 CPU).

인식 모델은 처음 쓸 때 한 번 내려받아 가상환경의 rapidocr 폴더에 저장되고, 그 뒤로는 인터넷 없이 동작한다.
OCR 결과에는 잡음이 섞일 수 있다 (예: 광합성 → 광합셩).
"""
import io, logging, re, threading

_engines = {}
_lock = threading.Lock()


def available():
    try:
        import rapidocr  # noqa: F401
        return True
    except Exception:
        return False


def engine(lang="korean"):
    with _lock:
        if lang not in _engines:
            from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
            rec = {"korean": LangRec.KOREAN, "en": LangRec.EN}.get(lang)
            if rec is None:
                raise ValueError(f"지원하지 않는 OCR 언어: {lang}")
            _engines[lang] = RapidOCR(params={
                "Global.log_level": "error",
                # 글줄 방향 분류기(0°/180°)는 멀쩡한 한국어 줄을 뒤집힌 것으로 잘못 보고 180° 돌려 읽는 일이 있어
                # (예: "그림 안에 들어 있는 글자입니다" → "른 극-를드") 끈다. 슬라이드에 뒤집힌 글자는 거의 없다.
                "Global.use_cls": False,
                "Rec.lang_type": rec,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
            })
            logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        return _engines[lang]


def to_png(blob, long_side=1600):
    """그림 파일 bytes(PNG·JPEG·GIF·BMP·TIFF…) → 흰 배경 PNG bytes. 읽을 수 없는 형식(EMF 등)이면 None."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(blob))
        im.load()
    except Exception:
        return None
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    if max(im.size) > long_side:
        f = long_side / max(im.size)
        im = im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def read(image, lang="korean"):
    """이미지(경로·PNG bytes·numpy 배열) → {"text", "chars"(공백 제외 글자 수), "score"(평균 신뢰도 0~1)}."""
    eng = engine(lang)
    with _lock:  # 엔진 하나를 여러 스레드가 같이 쓰지 않게
        r = eng(image)
    txts, scores = list(r.txts or []), list(r.scores or [])
    text = "\n".join(t.strip() for t in txts if t.strip())
    chars = len(re.sub(r"\s+", "", text))
    score = round(sum(scores) / len(scores), 3) if scores else 0.0
    return {"text": text, "chars": chars, "score": score}
