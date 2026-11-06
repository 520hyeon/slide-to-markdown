"""명령줄 변환: python -m slide2md <파일> [-o 출력.md] [--no-ocr] [--zip]

웹 화면 없이 같은 변환을 실행한다. 그림 위주 페이지 이미지는 출력 파일 옆 <이름>_images/에 저장된다.
"""
import argparse, shutil, sys, tempfile
from pathlib import Path

from .convert import build_zip, convert
from .markdown import render_document
from .model import Options


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="python -m slide2md", description="PDF·PPTX → 페이지별 Markdown")
    ap.add_argument("file", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="출력 경로 (기본: 원본 이름.md, --zip이면 .zip)")
    ap.add_argument("--no-ocr", action="store_true", help="그림 속 글자 OCR을 하지 않음")
    ap.add_argument("--lang", default="korean", choices=["korean", "en"], help="OCR 언어 (기본 korean: 한국어+영어)")
    ap.add_argument("--zip", action="store_true", help="문서 + 페이지별 .md + 이미지를 ZIP으로")
    a = ap.parse_args(argv)
    if not a.file.is_file():
        ap.error(f"파일이 없습니다: {a.file}")

    def progress(f, msg):
        print(f"\r[{f * 100:5.1f}%] {msg:<40}", end="", file=sys.stderr, flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        try:
            res = convert(a.file, tmp, Options(ocr=not a.no_ocr, ocr_lang=a.lang), progress=progress)
        except ValueError as e:
            print(f"\n오류: {e}", file=sys.stderr)
            return 1
        print(file=sys.stderr)
        images = Path(tmp) / "images"
        if a.zip:
            out = a.output or a.file.with_suffix(".zip")
            out.write_bytes(build_zip(res, images))
        else:
            out = a.output or a.file.with_suffix(".md")
            img_dir = out.with_name(out.stem + "_images")
            has_img = any(images.iterdir())
            out.write_text(render_document(res, with_images=has_img, image_prefix=f"{img_dir.name}/"),
                           encoding="utf-8", newline="\n")
            if has_img:
                shutil.copytree(images, img_dir, dirs_exist_ok=True)
    c = res.counts()
    print(f"{out}  ({len(res.pages)}쪽: 텍스트 {c['text']} / OCR {c['ocr']} / 그림 위주 {c['image']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
