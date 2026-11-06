"use strict";
// Slide to Markdown 화면: 올리기 → 진행 표시(주기적으로 상태 조회) → 미리보기 → 받기

const $ = (id) => document.getElementById(id);
const state = { jobs: [], selected: null, detail: null, md: "", timer: null, uploads: new Map(), maxMb: 200 };
const ACTIVE = new Set(["queued", "running"]);
const STATUS_LABEL = { queued: "대기", running: "변환 중", done: "완료", error: "실패", cancelled: "취소됨" };
const SOURCE_LABEL = { text: "텍스트", ocr: "텍스트 + OCR", image: "그림 위주" };

// ---------- 공통 ----------

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* 본문 없음 */ }
    throw new Error(msg);
  }
  return r;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (t.hidden = true), 2200);
}

function fmtSize(n) {
  return n >= 1048576 ? `${(n / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`;
}

// ---------- Markdown 미리보기 (이 앱이 만드는 문법만 다루는 작은 렌더러) ----------

function inline(s) {
  const keep = [];
  s = s.replace(/\\([\\`*_{}\[\]()#+\-.!|<>~=])/g, (_, c) => `\u0000${keep.push(esc(c)) - 1}\u0000`);
  s = s.replace(/`([^`]+)`/g, (_, c) => `\u0000${keep.push(`<code>${esc(c)}</code>`) - 1}\u0000`);
  s = esc(s);
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[+i]);
}

const LIST_RE = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const TABLE_SEP = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;

function cells(line) {
  return line.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "").split(/(?<!\\)\|/).map((c) => inline(c.trim()));
}

function renderList(lines) {
  let html = "";
  const stack = [];
  for (const ln of lines) {
    const m = ln.match(LIST_RE);
    const ind = m[1].length;
    const tag = /\d/.test(m[2]) ? "ol" : "ul";
    while (stack.length && ind < stack[stack.length - 1].indent) html += `</li></${stack.pop().tag}>`;
    const top = stack[stack.length - 1];
    if (!top || ind > top.indent) {
      html += tag === "ol" ? `<ol start="${parseInt(m[2], 10)}">` : "<ul>";
      stack.push({ indent: ind, tag });
    } else {
      html += "</li>";
      if (top.tag !== tag) {
        html += `</${top.tag}>${tag === "ol" ? `<ol start="${parseInt(m[2], 10)}">` : "<ul>"}`;
        top.tag = tag;
      }
    }
    html += `<li>${inline(m[3])}`;
  }
  while (stack.length) html += `</li></${stack.pop().tag}>`;
  return html;
}

function renderMarkdown(src, imageBase) {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  let pageNo = 0;
  while (i < lines.length) {
    const ln = lines[i];
    if (!ln.trim()) { i++; continue; }
    let m;
    if ((m = ln.match(/^(```|~~~)\s*(\w*)\s*$/))) {
      const fence = m[1];
      const body = [];
      for (i++; i < lines.length && lines[i].trim() !== fence; i++) body.push(lines[i]);
      i++;
      out.push(`<pre><code>${esc(body.join("\n"))}</code></pre>`);
    } else if ((m = ln.match(/^(#{1,6})\s+(.*)$/))) {
      const lv = m[1].length;
      const id = lv === 2 ? ` id="page-${++pageNo}"` : "";
      out.push(`<h${lv}${id}>${inline(m[2])}</h${lv}>`);
      i++;
    } else if ((m = ln.match(/^!\[([^\]]*)\]\(([^)\s]+)\)\s*$/))) {
      const src2 = m[2].startsWith("images/") ? imageBase + encodeURIComponent(m[2].slice(7)) : null;
      if (src2) out.push(`<p><a href="${esc(src2)}" target="_blank" rel="noopener"><img src="${esc(src2)}" alt="${esc(m[1])}" loading="lazy"></a></p>`);
      i++;
    } else if (ln.startsWith(">")) {
      const body = [];
      for (; i < lines.length && lines[i].startsWith(">"); i++) body.push(lines[i].replace(/^>\s?/, ""));
      const notes = /^\*\*발표자 노트\*\*/.test(body[0] || "");
      out.push(`<blockquote${notes ? ' class="notes"' : ""}>${renderMarkdown(body.join("\n"), imageBase)}</blockquote>`);
    } else if (ln.trim().startsWith("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      const head = cells(ln);
      const rows = [];
      for (i += 2; i < lines.length && lines[i].trim().startsWith("|"); i++) rows.push(cells(lines[i]));
      out.push("<table><thead><tr>" + head.map((c) => `<th>${c}</th>`).join("") + "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + r.map((c) => `<td>${c}</td>`).join("") + "</tr>").join("") + "</tbody></table>");
    } else if (LIST_RE.test(ln)) {
      const body = [];
      for (; i < lines.length && LIST_RE.test(lines[i]); i++) body.push(lines[i]);
      out.push(renderList(body));
    } else {
      const body = [];
      for (; i < lines.length && lines[i].trim() && !/^(#{1,6}\s|>|```|~~~|!\[)/.test(lines[i]) && !LIST_RE.test(lines[i]); i++) {
        body.push(lines[i]);
      }
      out.push(`<p>${body.map(inline).join("<br>")}</p>`);
    }
  }
  return out.join("\n");
}

// ---------- 올리기 ----------

function uploadError(msg) {
  const e = $("upload-error");
  e.textContent = msg || "";
  e.hidden = !msg;
}

function upload(file) {
  const ext = file.name.toLowerCase().match(/\.[^.]+$/)?.[0];
  if (ext !== ".pdf" && ext !== ".pptx") {
    uploadError(`${file.name}: PDF나 PPTX 파일만 올릴 수 있습니다.`);
    return;
  }
  if (file.size > state.maxMb * 1048576) {
    uploadError(`${file.name}: 파일이 너무 큽니다 (최대 ${state.maxMb}MB).`);
    return;
  }
  const key = `up-${Date.now()}-${Math.random()}`;
  state.uploads.set(key, { filename: file.name, size: file.size, progress: 0 });
  renderJobs();

  const fd = new FormData();
  fd.append("file", file);
  fd.append("ocr", $("opt-ocr").checked ? "true" : "false");
  fd.append("ocr_lang", $("opt-lang").value);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/jobs");
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      state.uploads.get(key).progress = e.loaded / e.total;
      renderJobs();
    }
  };
  xhr.onload = () => {
    state.uploads.delete(key);
    let body = {};
    try { body = JSON.parse(xhr.responseText); } catch (_) { /* 본문 없음 */ }
    if (xhr.status === 201) {
      if (!state.selected || !state.jobs.some((j) => j.id === state.selected && j.status === "done")) state.selected = body.id;
      refresh();
    } else {
      uploadError(`${file.name}: ${body.detail || `올리지 못했습니다 (${xhr.status})`}`);
      renderJobs();
    }
  };
  xhr.onerror = () => {
    state.uploads.delete(key);
    uploadError(`${file.name}: 서버에 연결하지 못했습니다. 서버 창이 켜져 있는지 확인하세요.`);
    renderJobs();
  };
  xhr.send(fd);
}

function setupDrop() {
  const drop = $("drop");
  const input = $("file");
  input.addEventListener("change", () => {
    uploadError("");
    [...input.files].forEach(upload);
    input.value = "";
  });
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
  });
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => {
    uploadError("");
    [...(e.dataTransfer?.files || [])].forEach(upload);
  });
  // 창 아무 데나 떨어뜨려도 브라우저가 파일을 열지 않게
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => { if (!drop.contains(e.target)) e.preventDefault(); });
}

// ---------- 작업 목록 ----------

function jobItem(j) {
  const pct = Math.round((j.progress || 0) * 100);
  const msgClass = j.status === "error" ? "err" : j.status === "done" ? "done" : "";
  const unit = j.kind === "pdf" ? "쪽" : "슬라이드";
  const msg = j.status === "error" ? j.error : j.status === "done" ? `${j.pages_total}${unit} · ${j.summary}` : j.message;
  const right = j.status === "running" ? `${pct}%` : j.status === "done" ? `${j.elapsed}초` : STATUS_LABEL[j.status] || "";
  const bar = ACTIVE.has(j.status)
    ? el("div", { class: "bar" + (j.status === "queued" ? " indeterminate" : "") }, el("i"))
    : null;
  if (bar && j.status === "running") bar.firstChild.style.width = `${Math.max(3, pct)}%`;
  const actions = el("div", { class: "job-actions" });
  if (ACTIVE.has(j.status)) {
    actions.append(el("button", { type: "button", class: "link danger", onclick: (e) => { e.stopPropagation(); cancelJob(j.id); } }, "취소"));
  } else {
    actions.append(el("button", { type: "button", class: "link danger", onclick: (e) => { e.stopPropagation(); deleteJob(j.id); } }, "지우기"));
  }
  return el("li", {
    class: "job" + (j.id === state.selected ? " selected" : ""),
    tabindex: 0,
    onclick: () => select(j.id),
    onkeydown: (e) => { if (e.key === "Enter") select(j.id); },
  },
  el("div", { class: "job-top" }, el("span", { class: "job-name", title: j.filename }, j.filename), el("span", { class: "kind" }, j.kind)),
  el("div", { class: "job-msg" }, el("span", { class: msgClass }, msg), el("span", {}, right)),
  bar, actions);
}

function renderJobs() {
  const ul = $("jobs");
  ul.replaceChildren();
  for (const u of state.uploads.values()) {
    const bar = el("div", { class: "bar" }, el("i"));
    bar.firstChild.style.width = `${Math.round(u.progress * 100)}%`;
    ul.append(el("li", { class: "job" },
      el("div", { class: "job-top" }, el("span", { class: "job-name" }, u.filename)),
      el("div", { class: "job-msg" }, el("span", {}, `올리는 중 · ${fmtSize(u.size)}`), el("span", {}, `${Math.round(u.progress * 100)}%`)),
      bar));
  }
  [...state.jobs].reverse().forEach((j) => ul.append(jobItem(j)));
  $("jobs-empty").hidden = state.jobs.length + state.uploads.size > 0;
  $("clear-done").hidden = !state.jobs.some((j) => !ACTIVE.has(j.status));
}

async function refresh() {
  try {
    state.jobs = await (await api("/api/jobs")).json();
  } catch (e) {
    uploadError(`서버에 연결하지 못했습니다: ${e.message}`);
    schedule(3000);
    return;
  }
  if (state.selected && !state.jobs.some((j) => j.id === state.selected)) {
    state.selected = null;
    showResult(null);
  }
  renderJobs();
  const sel = state.jobs.find((j) => j.id === state.selected);
  if (sel && sel.status === "done" && state.detail?.id !== sel.id) loadResult(sel.id);
  if (sel && sel.status !== "done") showResult(null, sel);
  schedule(state.jobs.some((j) => ACTIVE.has(j.status)) ? 700 : 0);
}

function schedule(ms) {
  clearTimeout(state.timer);
  if (ms) state.timer = setTimeout(refresh, ms);
}

function select(id) {
  state.selected = id;
  history.replaceState(null, "", id ? `#job=${id}` : location.pathname);
  renderJobs();
  const j = state.jobs.find((x) => x.id === id);
  if (j?.status === "done") loadResult(id);
  else showResult(null, j);
}

async function cancelJob(id) {
  try { await api(`/api/jobs/${id}/cancel`, { method: "POST" }); } catch (e) { toast(e.message); }
  refresh();
}

async function deleteJob(id) {
  try { await api(`/api/jobs/${id}`, { method: "DELETE" }); } catch (e) { toast(e.message); }
  if (state.selected === id) { state.selected = null; state.detail = null; showResult(null); }
  refresh();
}

// ---------- 결과 ----------

function showResult(detail, job) {
  $("result-body").hidden = !detail;
  $("result-empty").hidden = !!detail;
  const p = $("result-empty").querySelector("p");
  if (!detail) {
    state.detail = null;
    p.textContent = job && ACTIVE.has(job.status) ? `${job.filename} 변환 중… 끝나면 여기에 미리보기가 나옵니다.`
      : job?.status === "error" ? `${job.filename}: ${job.error}`
      : job?.status === "cancelled" ? `${job.filename}: 취소한 작업입니다.`
      : "변환이 끝난 작업을 고르면 여기에 미리보기가 나옵니다.";
  }
}

async function loadResult(id) {
  let detail, md, mdImg;
  try {
    detail = await (await api(`/api/jobs/${id}`)).json();
    [md, mdImg] = await Promise.all([
      api(`/api/jobs/${id}/markdown`).then((r) => r.text()),
      api(`/api/jobs/${id}/markdown?images=1`).then((r) => r.text()),
    ]);
  } catch (e) {
    toast(`결과를 불러오지 못했습니다: ${e.message}`);
    return;
  }
  if (state.selected !== id) return;
  state.detail = detail;
  state.md = md;
  showResult(detail);

  const unit = detail.kind === "pdf" ? "쪽" : "슬라이드";
  $("r-name").textContent = detail.filename;
  $("r-meta").textContent = `${detail.kind.toUpperCase()} · ${detail.pages_total}${unit} · ${fmtSize(detail.size)} · ${detail.elapsed}초` +
    (detail.ocr ? "" : " · OCR 끔");
  $("btn-md").href = `/api/jobs/${id}/markdown?download=1`;
  $("btn-zip").href = `/api/jobs/${id}/zip`;
  $("r-counts").replaceChildren(...["text", "ocr", "image"].map((k) =>
    el("span", { class: "count" }, el("span", { class: `dot ${k}` }), ` ${SOURCE_LABEL[k]}`, el("b", {}, String(detail.counts[k])))));
  $("r-warnings").replaceChildren(...(detail.warnings || []).map((w) => el("li", {}, w)));

  $("preview").innerHTML = renderMarkdown(mdImg, `/api/jobs/${id}/images/`);
  $("raw").textContent = md;
  $("preview").scrollTop = 0;
  $("page-filter").value = "";
  renderPages();
}

function renderPages() {
  const d = state.detail;
  const q = $("page-filter").value.trim().toLowerCase();
  const list = $("page-list");
  list.replaceChildren();
  for (const p of d.pages) {
    const label = p.title || (p.source === "image" ? "(그림 위주)" : "");
    if (q && !(`${p.number} ${label}`.toLowerCase().includes(q))) continue;
    list.append(el("li", {}, el("button", {
      type: "button",
      title: `${p.number}${d.kind === "pdf" ? "쪽" : "번 슬라이드"} · ${SOURCE_LABEL[p.source]}${p.reason ? ` (${p.reason})` : ""}`,
      onclick: (e) => gotoPage(p.number, e.currentTarget),
    }, el("span", { class: "no" }, String(p.number)), el("span", { class: "t" }, label || "—"), el("span", { class: `dot ${p.source}` }))));
  }
}

function gotoPage(n, btn) {
  showTab("preview");
  const h = document.getElementById(`page-${n}`);
  if (h) h.scrollIntoView({ behavior: "smooth", block: "start" });
  document.querySelectorAll("#page-list button.current").forEach((b) => b.classList.remove("current"));
  btn?.classList.add("current");
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on);
  });
  $("preview").hidden = name !== "preview";
  $("raw").hidden = name !== "raw";
}

async function copyMarkdown() {
  try {
    await navigator.clipboard.writeText(state.md);
    toast("Markdown을 복사했습니다.");
  } catch (_) {
    const r = document.createRange();
    showTab("raw");
    r.selectNodeContents($("raw"));
    getSelection().removeAllRanges();
    getSelection().addRange(r);
    toast("복사하지 못했습니다. 선택된 원문을 Ctrl+C로 복사하세요.");
  }
}

// ---------- 시작 ----------

async function init() {
  setupDrop();
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  $("btn-copy").addEventListener("click", copyMarkdown);
  $("page-filter").addEventListener("input", renderPages);
  $("clear-done").addEventListener("click", async () => {
    for (const j of state.jobs.filter((x) => !ACTIVE.has(x.status))) {
      try { await api(`/api/jobs/${j.id}`, { method: "DELETE" }); } catch (_) { /* 이미 없음 */ }
    }
    state.selected = null;
    showResult(null);
    refresh();
  });
  try {
    const s = await (await api("/api/status")).json();
    state.maxMb = s.max_upload_mb;
    $("limit-note").textContent = `PDF, PPTX · 여러 개 가능 · 최대 ${s.max_upload_mb}MB`;
    const pill = $("ocr-state");
    if (s.ocr_available) {
      pill.textContent = "OCR 사용 가능";
      pill.className = "pill ok";
    } else {
      pill.textContent = "OCR 없음 · 텍스트만";
      pill.className = "pill warn";
      pill.title = "rapidocr가 설치되어 있지 않아 그림 속 글자는 읽지 않습니다.";
      $("opt-ocr").checked = false;
      $("opt-ocr").disabled = true;
      $("opt-lang").disabled = true;
    }
  } catch (e) {
    $("ocr-state").textContent = "서버 연결 안 됨";
    $("ocr-state").className = "pill warn";
  }
  $("opt-ocr").addEventListener("change", () => ($("opt-lang").disabled = !$("opt-ocr").checked));
  const m = location.hash.match(/^#job=([0-9a-f]{6,32})$/);  // 새로 고침해도 보던 결과를 다시 엶
  if (m) state.selected = m[1];
  refresh();
}

init();
