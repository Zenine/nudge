import json

import pytest

from nudge.brain import parse_json_response


def test_parse_json_response_accepts_bare_json_array():
    assert parse_json_response('[{"type": "reminder", "name": "买牛奶"}]') == [
        {"type": "reminder", "name": "买牛奶"}
    ]


def test_parse_json_response_accepts_json_markdown_fence():
    raw = """```json
[{"type": "alarm", "time": "07:30"}]
```"""

    assert parse_json_response(raw) == [{"type": "alarm", "time": "07:30"}]


@pytest.mark.parametrize(
    "raw",
    [
        """```json
{"status": "done"}
```

""",
        """```json
{"status": "done"}
```

解析完成。""",
    ],
)
def test_parse_json_response_accepts_text_after_json_markdown_fence(raw):
    assert parse_json_response(raw) == {"status": "done"}


def test_parse_json_response_uses_first_json_fence_when_multiple_blocks_exist():
    raw = """```json
{"status": "done"}
```

```text
ignored
```"""

    assert parse_json_response(raw) == {"status": "done"}


def test_parse_json_response_keeps_invalid_json_decode_error():
    raw = """```json
{"status": "done",
```

说明文字不应吞掉真正的 JSON 错误。"""

    with pytest.raises(json.JSONDecodeError):
        parse_json_response(raw)
