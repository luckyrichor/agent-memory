from agent_memory.domain.dedup import dedup_hash, normalize_for_dedup


def test_case_whitespace_and_unicode_width_are_normalized() -> None:
    assert normalize_for_dedup("  Use   UV\tfor\nbuilds ") == "use uv for builds"
    assert normalize_for_dedup("ＵＳＥ ｕｖ") == "use uv"  # full-width forms (NFKC)
    assert dedup_hash("Use uv") == dedup_hash("  use   UV ")


def test_punctuation_and_wording_differences_are_not_duplicates() -> None:
    assert dedup_hash("Use uv") != dedup_hash("Use uv.")
    assert dedup_hash("Use uv") != dedup_hash("Always use uv")


def test_chinese_text_is_compared_exactly() -> None:
    assert dedup_hash("依赖冲突已解决") == dedup_hash(" 依赖冲突已解决 ")
    assert dedup_hash("依赖冲突已解决") != dedup_hash("依赖冲突已处理")
