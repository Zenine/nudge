import EventKit
import Foundation

func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

if CommandLine.arguments.count < 4 {
    fail("Usage: eventkit_reminders_mutate.swift <complete|delete> <list-name> <title> [due-date YYYY-MM-DD HH:mm]")
}

let operation = CommandLine.arguments[1]
let listName = CommandLine.arguments[2]
let title = CommandLine.arguments[3]
let dueDateText = CommandLine.arguments.count >= 5 ? CommandLine.arguments[4] : ""

if operation != "complete" && operation != "delete" {
    fail("Unsupported operation: \(operation)")
}

let store = EKEventStore()

func hasReadableReminderAccess(_ status: EKAuthorizationStatus) -> Bool {
    // rawValue 3 is `.authorized` on older macOS and `.fullAccess` on newer macOS.
    // rawValue 4 is write-only on newer macOS and is not enough for list queries.
    return status.rawValue == 3
}

func requestReminderAccessIfNeeded() -> Bool {
    let status = EKEventStore.authorizationStatus(for: .reminder)
    if hasReadableReminderAccess(status) {
        return true
    }
    if status.rawValue != 0 {
        return false
    }

    let semaphore = DispatchSemaphore(value: 0)
    var granted = false
    var requestError = ""

    if #available(macOS 14.0, *) {
        store.requestFullAccessToReminders { ok, error in
            granted = ok
            if let error {
                requestError = String(describing: error)
            }
            semaphore.signal()
        }
    } else {
        store.requestAccess(to: .reminder) { ok, error in
            granted = ok
            if let error {
                requestError = String(describing: error)
            }
            semaphore.signal()
        }
    }

    if semaphore.wait(timeout: .now() + 15) == .timedOut {
        fail("EventKit reminder access request timed out", code: 2)
    }
    if !requestError.isEmpty {
        fail("EventKit reminder access request failed: \(requestError)", code: 2)
    }
    return granted
}

if !requestReminderAccessIfNeeded() {
    fail("EventKit Reminders access denied or not readable", code: 2)
}

let calendars = store.calendars(for: .reminder).filter { $0.title == listName }
if calendars.isEmpty {
    fail("Missing reminder list: \(listName)", code: 3)
}

let predicate = store.predicateForReminders(in: calendars)
let semaphore = DispatchSemaphore(value: 0)
var fetched: [EKReminder] = []

store.fetchReminders(matching: predicate) { reminders in
    fetched = reminders ?? []
    semaphore.signal()
}

if semaphore.wait(timeout: .now() + 15) == .timedOut {
    fail("EventKit fetchReminders timed out", code: 4)
}

func parseLocalMinute(_ value: String) -> DateComponents? {
    if value.isEmpty {
        return nil
    }
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = TimeZone.current
    formatter.dateFormat = "yyyy-MM-dd HH:mm"
    guard let date = formatter.date(from: String(value.prefix(16))) else {
        fail("Invalid due-date; expected YYYY-MM-DD HH:mm: \(value)", code: 6)
    }
    return Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: date)
}

let dueComponents = parseLocalMinute(dueDateText)

func reminderMatchesDueDate(_ reminder: EKReminder) -> Bool {
    guard let dueComponents else {
        return true
    }
    guard let reminderDue = reminder.dueDateComponents else {
        return false
    }
    return reminderDue.year == dueComponents.year
        && reminderDue.month == dueComponents.month
        && reminderDue.day == dueComponents.day
        && reminderDue.hour == dueComponents.hour
        && reminderDue.minute == dueComponents.minute
}

let matches = fetched.filter { reminder in
    if reminder.title != title {
        return false
    }
    if !reminderMatchesDueDate(reminder) {
        return false
    }
    if operation == "complete" {
        return !reminder.isCompleted
    }
    return true
}

if dueComponents != nil && matches.count != 1 {
    fail("Precise reminder match expected 1, found \(matches.count)", code: 7)
}

var changed = 0
for reminder in matches {
    do {
        if operation == "complete" {
            reminder.isCompleted = true
            try store.save(reminder, commit: true)
        } else {
            try store.remove(reminder, commit: true)
        }
        changed += 1
    } catch {
        fail("EventKit \(operation) failed: \(error)", code: 5)
    }
}

print("matched=\(matches.count) changed=\(changed)")
