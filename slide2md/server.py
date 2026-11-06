"""로컬 웹 서버 (127.0.0.1 전용). 실행: run.bat 또는 python -m slide2md.server

- 127.0.0.1에만 바인딩한다 (같은 컴퓨터에서만 접속). 주소를 바꾸는 옵션은 일부러 두지 않았다.
- Host 헤더가 127.0.0.1·localhost가 아니면 거절한다 (DNS 리바인딩 방지).
- 다른 사이트에서 보낸 POST·DELETE(Origin이 로컬이 아님)는 거절한다.
- 변환은 백그라운드 스레드 하나에서 차례로 한다 (OCR이 CPU를 많이 씀). 화면은 진행 상태를 주기적으로 묻는다.
- 올린 파일과 결과는 작업 폴더(.work/)에만 두고, 서버를 다시 켜면 지운다.
"""
import argparse, json, os, re, shutil, socket, sys, threading, time, traceback, urllib.request, uuid, webbrowser
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, ocr
from .convert import SUPPORTED, build_zip, convert, detect_kind
from .markdown import render_document, summary_line
from .model import Cancelled, Options

HOST = "127.0.0.1"
LOCAL_HOSTS = ["127.0.0.1", "localhost"]
PORT = int(os.environ.get("SLIDE2MD_PORT", "8766"))
MAX_UPLOAD_MB = int(os.environ.get("SLIDE2MD_MAX_MB", "200"))
KEEP_JOBS = 30
BASE = Path(__file__).resolve().parent.parent
WORK_DIR = Path(os.environ.get("SLIDE2MD_WORK_DIR", BASE / ".work"))
STATIC = Path(__file__).resolve().parent / "static"
ACTIVE = ("queued", "running")
_IMAGE_NAME = re.compile(r"^p\d{3}(_\d+)?\.[A-Za-z0-9]{1,5}$")


@dataclass
class Job:
    id: str
    filename: str
    kind: str
    dir: Path
    options: Options
    size: int = 0
    status: str = "queued"          # queued | running | done | error | cancelled
    progress: float = 0.0
    message: str = "대기 중"
    error: str = ""
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0
    result: object = None
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def input_path(self):
        return self.dir / f"input.{self.kind}"

    def info(self, detail=False):
        d = {"id": self.id, "filename": self.filename, "kind": self.kind, "size": self.size,
             "status": self.status, "progress": round(self.progress, 3), "message": self.message,
             "error": self.error, "created": self.created, "ocr": self.options.ocr,
             "elapsed": round((self.finished or time.time()) - self.started, 1) if self.started else 0}
        if self.result is not None:
            d["pages_total"] = len(self.result.pages)
            d["counts"] = self.result.counts()
            d["summary"] = summary_line(self.result)
            if detail:
                d["warnings"] = self.result.warnings
                d["pages"] = [p.summary() for p in self.result.pages]
        return d


class JobStore:
    def __init__(self, work_dir):
        self.work_dir = Path(work_dir)
        if self.work_dir.exists():  # 지난 실행의 업로드·결과는 지움
            shutil.rmtree(self.work_dir, ignore_errors=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="convert")

    def new_dir(self):
        jid = uuid.uuid4().hex[:12]
        d = self.work_dir / jid
        d.mkdir()
        return jid, d

    def add(self, job):
        with self.lock:
            self.jobs[job.id] = job
        self.pool.submit(self._run, job)
        self.prune()

    def get(self, jid):
        job = self.jobs.get(jid)
        if job is None:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        return job

    def ordered(self):
        with self.lock:
            return sorted(self.jobs.values(), key=lambda j: j.created)

    def queue_position(self, job):
        return sum(1 for j in self.ordered() if j.status in ACTIVE and j.created < job.created)

    def remove(self, jid):
        with self.lock:
            job = self.jobs.pop(jid, None)
        if job:
            job.cancel.set()
            if job.status != "running":  # 실행 중이면 끝난 뒤 _run이 지움
                shutil.rmtree(job.dir, ignore_errors=True)
        return job

    def prune(self):
        done = [j for j in self.ordered() if j.status not in ACTIVE]
        for j in done[:max(0, len(self.jobs) - KEEP_JOBS)]:
            self.remove(j.id)

    def _run(self, job):
        if job.cancel.is_set():
            job.status, job.message, job.finished = "cancelled", "취소됨", time.time()
            job.input_path.unlink(missing_ok=True)
            return
        job.status, job.started, job.message = "running", time.time(), "시작하는 중"

        def progress(f, msg):
            job.progress = max(job.progress, min(float(f), 1.0))
            job.message = msg

        try:
            res = convert(job.input_path, job.dir, job.options, filename=job.filename,
                          progress=progress, cancel=job.cancel.is_set)
            job.result = res
            job.status, job.progress, job.message = "done", 1.0, "완료"
        except Cancelled:
            job.status, job.message = "cancelled", "취소됨"
        except ValueError as e:
            job.status, job.error, job.message = "error", str(e), "실패"
        except Exception as e:
            traceback.print_exc()
            job.status, job.error, job.message = "error", f"변환 중 오류가 났습니다: {type(e).__name__}: {e}", "실패"
        finally:
            job.finished = time.time()
            job.input_path.unlink(missing_ok=True)  # 원본은 변환이 끝나면 지움 (결과·이미지만 남김)
            if job.id not in self.jobs:
                shutil.rmtree(job.dir, ignore_errors=True)

    def shutdown(self):
        for j in self.ordered():
            j.cancel.set()
        self.pool.shutdown(wait=False, cancel_futures=True)


def _attachment(filename):
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "download"
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"}


def _safe_filename(name):
    name = Path(name or "").name
    name = re.sub(r"[\x00-\x1f\x7f<>:\"/\\|?*]", "_", name).strip(" .")
    return name[:180] or "upload"


def create_app(work_dir=None):
    store = JobStore(work_dir or WORK_DIR)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        store.shutdown()

    app = FastAPI(title="Slide to Markdown", version=__version__, docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.store = store
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).hostname not in LOCAL_HOSTS:
                return JSONResponse({"detail": "다른 사이트에서 보낸 요청은 받지 않습니다."}, status_code=403)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' blob: data:; object-src 'none'; frame-ancestors 'none'")
        return resp

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/status")
    def status():
        return {"app": "slide-to-markdown", "version": __version__, "ocr_available": ocr.available(),
                "max_upload_mb": MAX_UPLOAD_MB, "formats": sorted(SUPPORTED)}

    @app.get("/api/jobs")
    def list_jobs():
        out = []
        for j in store.ordered():
            d = j.info()
            if j.status == "queued":
                n = store.queue_position(j)
                d["message"] = f"대기 중 (앞에 {n}개)" if n else "곧 시작"
            out.append(d)
        return out

    @app.post("/api/jobs", status_code=201)
    async def create_job(file: UploadFile = File(...), ocr_on: bool = Form(True, alias="ocr"),
                         ocr_lang: str = Form("korean")):
        filename = _safe_filename(file.filename)
        kind = SUPPORTED.get(Path(filename).suffix.lower())
        if not kind:
            raise HTTPException(400, "PDF(.pdf)나 PPTX(.pptx) 파일만 올릴 수 있습니다.")
        if ocr_lang not in ("korean", "en"):
            raise HTTPException(400, "OCR 언어는 korean 또는 en입니다.")
        jid, d = store.new_dir()
        dest, size, limit = d / f"input.{kind}", 0, MAX_UPLOAD_MB * 1024 * 1024
        try:
            with open(dest, "wb") as f:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_MB}MB).")
                    f.write(chunk)
            if size == 0:
                raise HTTPException(400, "빈 파일입니다.")
            try:
                detect_kind(dest, filename)
            except ValueError as e:
                raise HTTPException(400, str(e))
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
        job = Job(id=jid, filename=filename, kind=kind, dir=d, size=size,
                  options=Options(ocr=ocr_on, ocr_lang=ocr_lang))
        store.add(job)
        return job.info()

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str):
        return store.get(jid).info(detail=True)

    @app.post("/api/jobs/{jid}/cancel")
    def cancel_job(jid: str):
        job = store.get(jid)
        if job.status in ACTIVE:
            job.cancel.set()
            job.message = "취소하는 중"
        return job.info()

    @app.delete("/api/jobs/{jid}")
    def delete_job(jid: str):
        store.get(jid)
        store.remove(jid)
        return {"ok": True}

    def done_job(jid):
        job = store.get(jid)
        if job.status != "done" or job.result is None:
            raise HTTPException(409, "아직 변환이 끝나지 않았습니다.")
        return job

    @app.get("/api/jobs/{jid}/markdown")
    def markdown(jid: str, images: bool = False, download: bool = False):
        """images=1: 그림 위주 페이지에 이미지 링크(images/…)를 넣은 판 (화면 미리보기·ZIP과 같음)."""
        job = done_job(jid)
        md = render_document(job.result, with_images=images)
        headers = _attachment(Path(job.filename).stem + ".md") if download else {}
        return Response(md, media_type="text/markdown; charset=utf-8", headers=headers)

    @app.get("/api/jobs/{jid}/zip")
    def download_zip(jid: str):
        job = done_job(jid)
        data = build_zip(job.result, job.dir / "images")
        return Response(data, media_type="application/zip", headers=_attachment(Path(job.filename).stem + ".zip"))

    @app.get("/api/jobs/{jid}/images/{name}")
    def image(jid: str, name: str):
        job = done_job(jid)
        if not _IMAGE_NAME.match(name) or not any(name in p.images for p in job.result.pages):
            raise HTTPException(404, "이미지가 없습니다.")
        return FileResponse(job.dir / "images" / name)

    return app


# ---------- 실행 ----------

def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) == 0


def _is_ours(port):
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/status", timeout=2) as r:
            return json.load(r).get("app") == "slide-to-markdown"
    except Exception:
        return False


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Slide to Markdown 로컬 웹 서버 (127.0.0.1 전용)")
    ap.add_argument("--port", type=int, default=PORT, help=f"포트 (기본 {PORT}, 환경 변수 SLIDE2MD_PORT)")
    ap.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    a = ap.parse_args(argv)
    url = f"http://{HOST}:{a.port}"
    if _port_in_use(a.port):
        if _is_ours(a.port):
            print(f"이미 실행 중입니다: {url}")
            if not a.no_browser:
                webbrowser.open(url)
            return 0
        print(f"[오류] 포트 {a.port}을(를) 다른 프로그램이 쓰고 있습니다. SLIDE2MD_PORT로 다른 포트를 지정하세요.")
        return 1

    import uvicorn
    server = uvicorn.Server(uvicorn.Config(create_app(), host=HOST, port=a.port, log_level="warning"))

    def announce():
        while not server.started:
            if server.should_exit:
                return
            time.sleep(0.1)
        ocr_note = "OCR 사용 가능" if ocr.available() else "OCR 없음 (rapidocr 미설치: 텍스트만 추출)"
        print(f"Slide to Markdown 실행 중: {url}  [{ocr_note}]", flush=True)
        print("끄려면 이 창을 닫거나 Ctrl+C를 누르세요.", flush=True)
        if not a.no_browser:
            webbrowser.open(url)

    threading.Thread(target=announce, daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
