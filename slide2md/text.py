"""텍스트 정리, 글머리표 판별, Markdown 이스케이프."""
import re

_PUA = "\ue000-\uf8ff"  # Wingdings 같은 기호 글꼴의 글머리표가 이 영역으로 나옴
_BAD = re.compile(rf"[{_PUA}\ufffd\u200b\ufeff\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BULLET = re.compile(rf"^\s*(?:[{_PUA}•●○◦▪▫■□◆◇►▶▷‣⁃∙·✓✔➢➤❖]\s*|[-–—*]\s+)")
_BULLET_ONLY = re.compile(rf"^\s*[{_PUA}•●○◦▪▫■□◆◇►▶▷‣⁃∙·✓✔➢➤❖\-–—*]+\s*$")


def clean(s):
    s = _BAD.sub("", s.replace("\u00a0", " ").replace("\v", " "))
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def split_bullet(raw):
    """글머리표로 시작하면 (True, 나머지), 아니면 (False, 원문)."""
    m = _BULLET.match(raw)
    if m and raw[m.end():].strip():
        return True, raw[m.end():]
    return False, raw


def bullet_only(raw):
    return bool(_BULLET_ONLY.match(raw))


def escape_md(s):
    """슬라이드 글자가 Markdown 문법으로 해석되지 않게 최소한만 이스케이프."""
    s = s.replace("\\", "\\\\")
    s = re.sub(r"([`*])", r"\\\1", s)
    s = re.sub(r"(?<![\w\\])_|_(?!\w)", r"\\_", s)       # 단어 안의 _ (snake_case)는 그대로
    s = re.sub(r"<(?=[A-Za-z/!?])", r"\\<", s)           # HTML 태그처럼 보이는 것만
    s = s.replace("](", "\\](").replace("~~", "\\~\\~")
    s = re.sub(r"^([#>+=|])", r"\\\1", s)
    s = re.sub(r"^-(\s|$|-)", r"\\-\1", s)
    s = re.sub(r"^(\d{3,})([.)])(\s|$)", r"\1\\\2\3", s)  # 2024. 같은 연도는 번호 목록이 아님
    return s


def escape_cell(s):
    return escape_md(clean(s)).replace("|", "\\|")


def md_table(rows):
    """rows: [[셀 문자열]] (첫 행은 머리글) → GFM 표. 빈 열·빈 행은 없앤다."""
    rows = [[clean(c or "") for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    keep = [j for j in range(n) if any(r[j] for r in rows)]
    rows = [[r[j] for j in keep] for r in rows]
    if not keep:
        return ""
    out = ["| " + " | ".join(escape_cell(c) for c in rows[0]) + " |",
           "|" + "|".join(" --- " for _ in keep) + "|"]
    out += ["| " + " | ".join(escape_cell(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(out)


def md_list(items):
    """items: [(level, text, ordered)] → 중첩 목록. 단계는 앞 항목보다 한 단계까지만 깊어진다."""
    out, stack, nums = [], [], {}  # stack[i] = (들여쓰기, 기호+공백 너비): 하위 항목은 부모 내용 위치에 맞춤
    for level, text, ordered in items:
        level = max(0, min(level, len(stack)))
        del stack[level:]
        for k in [k for k in nums if k > level]:
            del nums[k]
        if ordered:
            nums[level] = nums.get(level, 0) + 1
            mark = f"{nums[level]}."
        else:
            nums.pop(level, None)
            mark = "-"
        indent = stack[-1][0] + stack[-1][1] if stack else 0
        body = re.sub(r"^(\d+)([.)])(\s|$)", r"\1\\\2\3", escape_md(text))  # "- 1. x"가 중첩 목록이 되지 않게
        out.append(" " * indent + f"{mark} {body}")
        stack.append((indent, len(mark) + 1))
    return "\n".join(out)
