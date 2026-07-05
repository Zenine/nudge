from __future__ import annotations

import io
from pathlib import Path
from zipfile import ZipFile

import pytest

import nudge.health as health


NORMAL_HEALTH_XML = """<HealthData><Record type="HKQuantityTypeIdentifierStepCount" startDate="2026-07-01 08:00:00 +0000" endDate="2026-07-01 08:01:00 +0000" value="123" sourceName="test" unit="count"/></HealthData>"""

MALICIOUS_HEALTH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
<HealthData>&xxe;<Record type="HKQuantityTypeIdentifierStepCount" startDate="2026-07-01 08:00:00 +0000" endDate="2026-07-01 08:01:00 +0000" value="1" sourceName="test" unit="count"/></HealthData>
"""


def _write_health_zip(path: Path, xml: str) -> Path:
    with ZipFile(path, "w") as zf:
        zf.writestr("apple_health_export/export.xml", xml)
    return path


def test_parse_small_health_xml_zip_keeps_step_summary(tmp_path: Path) -> None:
    export_zip = _write_health_zip(tmp_path / "export.zip", NORMAL_HEALTH_XML)

    result = health.parse_apple_health_export(export_zip)

    assert result.export_xml_name == "apple_health_export/export.xml"
    assert result.daily_summaries
    assert result.daily_summaries[0]["date"] == "2026-07-01"
    assert result.daily_summaries[0]["steps"] == 123
    assert result.daily_summaries[0]["source_counts"] == {"test": 1}


def test_parse_health_xml_rejects_doctype_entity_zip(tmp_path: Path) -> None:
    export_zip = _write_health_zip(tmp_path / "malicious.zip", MALICIOUS_HEALTH_XML)

    with pytest.raises(Exception):
        health.parse_apple_health_export(export_zip)


def test_assert_health_xml_size_rejects_oversized_entry() -> None:
    class FakeInfo:
        filename = "apple_health_export/export.xml"
        file_size = health.MAX_HEALTH_EXPORT_XML_BYTES + 1

    with pytest.raises(ValueError, match="too large"):
        health._assert_health_xml_size(FakeInfo())


def test_find_health_export_xml_rejects_oversized_candidate() -> None:
    class FakeInfo:
        filename = "apple_health_export/export.xml"
        file_size = health.MAX_HEALTH_EXPORT_XML_BYTES + 1

    class FakeZip:
        def infolist(self):
            return [FakeInfo()]

        def open(self, info):
            return io.BytesIO(NORMAL_HEALTH_XML.encode("utf-8"))

    with pytest.raises(ValueError, match="too large"):
        health._find_health_export_xml(FakeZip())
