"""변환 진입점: 파일 형식 판별 → 페이지 읽기 → Result. Markdown·ZIP 만들기."""
import io, zipfile
from pathlib import Path

from . import ocr
from .markdown import render_document, render_page
from .model import Cancelled, Options, Result

SUPPORTED = {".pdf": "pdf", ".pptx": "pptx"}
MAGIC = {"pdf": b"%PDF-", "pptx": b"PK\x03\x04"}

__all__ = ["Cancelled", "SUPPORTED", "convert", "detect_kind", "build_zip"]


def detect_kind(path, filename=None):
    """확장자와 파일 앞부분으로 형식 판별. 맞지 않으면 ValueError."""
    ext = Path(filename or path).suffix.lower()
    kind = SUPPORTED.get(ext)
    if not kind:
        raise ValueError(f"지원하지 않는 형식입니다: {ext or '(확장자 없음)'} — PDF, PPTX만 됩니다.")
    with open(path, "rb") as f:
        head = f.read(1024)
    if kind == "pdf" and MAGIC["pdf"] not in head:
        raise ValueError("PDF 파일이 아닙니다 (파일 앞부분에 %PDF- 표시가 없음).")
    if kind == "pptx" and not head.startswith(MAGIC["pptx"]):
        raise ValueError("PPTX 파일이 아닙니다. 옛 .ppt 형식이면 PowerPoint에서 .pptx로 저장한 뒤 올려 주세요.")
    return kind


def convert(path, out_dir, options=None, filename=None, progress=None, cancel=None):
    """path의 PDF·PPTX를 변환. 그림 위주 페이지의 이미지는 out_dir/images/에 저장.

    progress(비율 0~1, 메시지), cancel() → True면 Cancelled를 던진다.
    """
    opt = options or Options()
    progress = progress or (lambda f, m: None)
    cancel = cancel or (lambda: False)
    filename = filename or Path(path).name
    kind = detect_kind(path, filename)
    images = Path(out_dir) / "images"
    images.mkdir(parents=True, exist_ok=True)

    warnings, ocr_read = [], None
    if opt.ocr:
        if ocr.available():
            progress(0.0, "OCR 엔진 준비 중 (처음 한 번은 모델을 내려받습니다)")
            ocr.engine(opt.ocr_lang)
            ocr_read = lambda img: ocr.read(img, opt.ocr_lang)  # noqa: E731
        else:
            warnings.append("OCR 패키지(rapidocr)가 없어 그림 속 글자는 읽지 않았습니다.")
    else:
        warnings.append("OCR을 끄고 변환했습니다. 그림이 큰 페이지는 그림 위주로 표시합니다.")

    progress(0.0, "파일 여는 중")
    if kind == "pdf":
        from .pdf_reader import read_pdf
        pages = read_pdf(str(path), opt, images, progress, cancel, ocr_read)
    else:
        from .pptx_reader import read_pptx
        pages = list(read_pptx(str(path), opt, images, progress, cancel, ocr_read))
    if not pages:
        raise ValueError("페이지가 없는 파일입니다.")
    progress(1.0, "완료")
    return Result(filename=filename, kind=kind, pages=pages, warnings=warnings)


def build_zip(result, images_dir):
    """<이름>.md (이미지 링크 포함) + pages/NNN.md + images/ → ZIP bytes."""
    stem = Path(result.filename).stem
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{stem}.md", render_document(result, with_images=True))
        for p in result.pages:
            z.writestr(f"pages/{p.number:03d}.md", render_page(p, result.kind, True, "../images/"))
            for name in p.images:
                f = Path(images_dir) / name
                if f.exists():
                    z.write(f, f"images/{name}")
    return buf.getvalue()
