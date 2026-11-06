from slide2md.model import Options, Page, judge
from slide2md.text import clean, escape_md, md_list, md_table, split_bullet


def test_clean_removes_control_and_symbol_font_chars():
    assert clean("  항목\x07   하나 ") == "항목 하나"


def test_split_bullet():
    assert split_bullet("• 첫째") == (True, "첫째")
    assert split_bullet("둘째") == (True, "둘째")
    assert split_bullet("- 셋째") == (True, "셋째")
    assert split_bullet("-5도") == (False, "-5도")       # 음수는 글머리표가 아님
    assert split_bullet("•") == (False, "•")             # 글머리표만 있는 줄


def test_escape_md_keeps_text_literal():
    assert escape_md("# 해시로 시작") == "\\# 해시로 시작"
    assert escape_md("a*b*c") == "a\\*b\\*c"
    assert escape_md("snake_case_name") == "snake_case_name"
    assert escape_md("_강조_") == "\\_강조\\_"
    assert escape_md("<script>") == "\\<script>"
    assert escape_md("x < y") == "x < y"
    assert escape_md("2024. 3. 15.") == "2024\\. 3. 15."
    assert escape_md("1. 소개") == "1. 소개"           # 원래 번호 목록은 그대로
    assert escape_md("[링크](주소)") == "[링크\\](주소)"


def test_md_table_drops_empty_columns_and_escapes_pipes():
    md = md_table([["이름", "", "값"], ["a|b", "", "1"], ["", "", ""]])
    assert md.splitlines() == ["| 이름 | 값 |", "| --- | --- |", "| a\\|b | 1 |"]
    assert md_table([["", ""]]) == ""


def test_md_list_nesting_aligns_to_parent_content():
    md = md_list([(0, "하나", False), (1, "하위", False), (3, "너무 깊음", False), (0, "번호", True), (1, "번호 하위", False),
                  (0, "번호 둘", True)])
    assert md.splitlines() == ["- 하나", "  - 하위", "    - 너무 깊음", "1. 번호", "   - 번호 하위", "2. 번호 둘"]
    assert md_list([(0, "1. 글자로 쓴 번호", False)]) == "- 1\\. 글자로 쓴 번호"


def _page():
    return Page(number=1)


def test_judge_figure_with_rich_ocr_is_ocr():
    p = _page()
    judge(p, Options(), [(0.3, {"text": "가" * 200, "chars": 200, "score": 0.95})])
    assert (p.source, p.ocr_chars, p.ocr_density) == ("ocr", 200, 667)


def test_judge_big_figure_with_weak_ocr_is_image():
    p = _page()
    judge(p, Options(), [(0.5, {"text": "업로드", "chars": 3, "score": 0.9})])
    assert p.source == "image" and "3자" in p.reason and "밀도" in p.reason


def test_judge_low_confidence_is_image():
    p = _page()
    judge(p, Options(), [(0.2, {"text": "가" * 150, "chars": 150, "score": 0.5})])
    assert p.source == "image" and "신뢰도" in p.reason


def test_judge_small_figure_is_not_judged():
    p = _page()
    judge(p, Options(), [(0.05, {"text": "로고", "chars": 2, "score": 0.9})])
    assert p.source == "ocr"
    p = _page()
    judge(p, Options(), [(0.05, {"text": "", "chars": 0, "score": 0.0})])
    assert p.source == "text"
