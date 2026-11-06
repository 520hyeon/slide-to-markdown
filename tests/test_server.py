import io, time, zipfile

import pytest
from fastapi.testclient import TestClient

from slide2md.server import create_app

BASE = "http://127.0.0.1:8766"


@pytest.fixture
def client(tmp_path, no_ocr):
    app = create_app(tmp_path / "work")
    with TestClient(app, base_url=BASE) as c:
        c.work = tmp_path / "work"
        yield c


def _upload(client, path, name=None, **form):
    with open(path, "rb") as f:
        return client.post("/api/jobs", files={"file": (name or path.name, f)}, data=form)


def _wait(client, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.1)
    raise AssertionError("변환이 끝나지 않음")


def test_index_and_static(client):
    r = client.get("/")
    assert r.status_code == 200 and "Slide to Markdown" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
    s = client.get("/api/status").json()
    assert s["app"] == "slide-to-markdown" and s["ocr_available"] is False and s["formats"] == [".pdf", ".pptx"]


def test_convert_flow(client, sample_pdf):
    r = _upload(client, sample_pdf, "발표 자료.pdf", ocr="false")
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    j = _wait(client, jid)
    assert j["status"] == "done" and j["progress"] == 1.0 and j["pages_total"] == 5
    assert j["counts"] == {"text": 3, "ocr": 0, "image": 2}
    assert [p["number"] for p in j["pages"]] == [1, 2, 3, 4, 5]
    assert j["pages"][4]["source_label"] == "그림 위주" and "text" not in j["pages"][0]
    assert not (client.work / jid / "input.pdf").exists()   # 변환 뒤 원본은 지움

    md = client.get(f"/api/jobs/{jid}/markdown")
    assert md.headers["content-type"].startswith("text/markdown") and md.text.startswith("# 발표 자료\n")
    assert "content-disposition" not in md.headers
    dl = client.get(f"/api/jobs/{jid}/markdown", params={"download": 1})
    assert "filename*=UTF-8''%EB%B0%9C%ED%91%9C%20%EC%9E%90%EB%A3%8C.md" in dl.headers["content-disposition"]
    assert "](images/p005.png)" in client.get(f"/api/jobs/{jid}/markdown", params={"images": 1}).text

    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/jobs/{jid}/zip").content))
    assert "발표 자료.md" in z.namelist() and "images/p005.png" in z.namelist()

    img = client.get(f"/api/jobs/{jid}/images/p005.png")
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.get(f"/api/jobs/{jid}/images/p001.png").status_code == 404
    assert client.get(f"/api/jobs/{jid}/images/..%2F..%2Fsecret.png").status_code == 404

    assert [x["id"] for x in client.get("/api/jobs").json()] == [jid]
    assert client.delete(f"/api/jobs/{jid}").json() == {"ok": True}
    assert client.get(f"/api/jobs/{jid}").status_code == 404
    assert not (client.work / jid).exists()


def test_pptx_upload(client, sample_pptx):
    jid = _upload(client, sample_pptx, ocr="false").json()["id"]
    j = _wait(client, jid)
    assert j["status"] == "done" and j["kind"] == "pptx" and j["pages_total"] == 6


def test_rejects_bad_uploads(client, tmp_path):
    bad = tmp_path / "x.txt"
    bad.write_text("hello")
    r = _upload(client, bad)
    assert r.status_code == 400 and "PDF" in r.json()["detail"]
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"hello world")
    r = _upload(client, fake)
    assert r.status_code == 400 and "PDF 파일이 아닙니다" in r.json()["detail"]
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    assert _upload(client, empty).status_code == 400
    assert _upload(client, fake, ocr_lang="fr").status_code == 400
    assert list(client.work.iterdir()) == []                 # 거절한 업로드는 남기지 않음


def test_markdown_before_done_is_409(client, sample_pdf, monkeypatch):
    import slide2md.server as S
    started = []

    def slow_convert(*a, **k):
        started.append(1)
        cancel = k["cancel"]
        while not cancel():
            time.sleep(0.02)
        raise S.Cancelled()

    monkeypatch.setattr(S, "convert", slow_convert)
    jid = _upload(client, sample_pdf).json()["id"]
    second = _upload(client, sample_pdf).json()["id"]
    assert client.get(f"/api/jobs/{jid}/markdown").status_code == 409
    msgs = {j["id"]: j["message"] for j in client.get("/api/jobs").json()}
    assert msgs[second] in ("대기 중 (앞에 1개)", "곧 시작")
    assert client.post(f"/api/jobs/{second}/cancel").status_code == 200
    assert client.post(f"/api/jobs/{jid}/cancel").json()["message"] == "취소하는 중"
    assert _wait(client, jid)["status"] == "cancelled"
    assert _wait(client, second)["status"] == "cancelled"


def test_rejects_foreign_host_and_origin(client, sample_pdf):
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/status", headers={"host": "localhost:8766"}).status_code == 200
    with open(sample_pdf, "rb") as f:
        r = client.post("/api/jobs", files={"file": ("a.pdf", f)}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    with open(sample_pdf, "rb") as f:
        r = client.post("/api/jobs", files={"file": ("a.pdf", f)}, headers={"origin": BASE}, data={"ocr": "false"})
    assert r.status_code == 201


def test_upload_size_limit(client, sample_pdf, monkeypatch):
    import slide2md.server as S
    monkeypatch.setattr(S, "MAX_UPLOAD_MB", 0)
    r = _upload(client, sample_pdf)
    assert r.status_code == 413
    assert list(client.work.iterdir()) == []


def test_server_binds_localhost_only():
    import slide2md.server as S
    assert S.HOST == "127.0.0.1"
