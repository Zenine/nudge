"""Tests for user-facing error reports."""


from nudge.errors import ErrorReport


def test_error_report_render_is_pure_formatting(monkeypatch):
    monkeypatch.setattr(
        "nudge.errors.log_error_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render must not write runtime logs")),
        raising=False,
    )
    error = ErrorReport(
        code="TEST_ERROR",
        title="测试错误",
        detail="用于固定 render 契约",
        next_steps=("第一步", "第二步"),
        raw_error="raw detail",
    )

    rendered = error.render(indent="  ")

    assert "  ERROR [TEST_ERROR]: 测试错误" in rendered
    assert "  1. 第一步" in rendered
    assert "  原始错误：raw detail" in rendered
