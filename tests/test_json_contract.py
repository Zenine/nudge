"""Public-safe tests for shared JSON response contracts."""

from nudge.json_contract import CLI_SCHEMA_VERSION, versioned_payload


def test_versioned_payload_adds_stable_schema_version():
    payload = versioned_payload({"ok": True, "value": 42})

    assert payload == {
        "schema_version": CLI_SCHEMA_VERSION,
        "ok": True,
        "value": 42,
    }


def test_versioned_payload_replaces_caller_schema_version():
    payload = versioned_payload({"schema_version": "old", "ok": True})

    assert payload == {"schema_version": CLI_SCHEMA_VERSION, "ok": True}
