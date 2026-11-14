"""离线执行实际 Swift 分发代码，防止完成操作误入删除分支。"""

import json
import shutil
import subprocess

import pytest

from nudge.apple.reminders import EVENTKIT_MUTATE_SCRIPT


@pytest.mark.parametrize("operation", ["complete", "complete-id", "delete"])
def test_eventkit_completion_saves_instead_of_deleting(tmp_path, operation):
    swift = shutil.which("swift")
    if swift is None:
        pytest.skip("此回归测试需要 Swift；不访问真实 EventKit 或 Apple Reminders")

    source = EVENTKIT_MUTATE_SCRIPT.read_text()
    dispatch = "var changed = 0\n" + source.split("\nvar changed = 0\n", 1)[1]
    harness = tmp_path / "reminder-dispatch.swift"
    harness.write_text(
        """import Foundation
final class FakeReminder {
    var isCompleted = false
    var url: URL?
    var notes: String?
}
final class FakeStore {
    var saved = 0
    var removed = 0
    func save(_ reminder: FakeReminder, commit: Bool) throws { saved += 1 }
    func remove(_ reminder: FakeReminder, commit: Bool) throws { removed += 1 }
}
func fail(_ message: String, code: Int32 = 1) -> Never { fatalError(message) }
let operation = CommandLine.arguments[1]
let lookupExternalId = "nudge://reminder/offline-test"
let notesText = "offline-test"
let reminder = FakeReminder()
let matches = [reminder]
let store = FakeStore()
"""
        + dispatch
        + """
let result: [String: Any] = [
    "completed": reminder.isCompleted,
    "saved": store.saved,
    "removed": store.removed
]
let data = try JSONSerialization.data(withJSONObject: result)
print(String(data: data, encoding: .utf8)!)
"""
    )
    result = subprocess.run(
        [swift, str(harness), operation],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    actual = json.loads(result.stdout.splitlines()[-1])
    deleting = operation == "delete"
    assert actual == {
        "completed": not deleting,
        "saved": 0 if deleting else 1,
        "removed": 1 if deleting else 0,
    }
