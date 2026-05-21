import EventKit
import Foundation

func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

func sanitize(_ value: String) -> String {
    return value
        .replacingOccurrences(of: "\t", with: " ")
        .replacingOccurrences(of: "\n", with: " ")
        .replacingOccurrences(of: "\r", with: " ")
}

let args = Array(CommandLine.arguments.dropFirst())
let listOnly = args.first == "--lists"
let requestedListName = args.first
let requestedDateText = args.dropFirst().first
let requestedMode = args.dropFirst(2).first ?? "incomplete"
let store = EKEventStore()

if !listOnly && requestedMode != "incomplete" && requestedMode != "completed" {
    fail("Invalid mode: \(requestedMode); expected incomplete or completed", code: 4)
}

func hasReadableReminderAccess(_ status: EKAuthorizationStatus) -> Bool {
    // rawValue 3 is `.authorized` on older macOS and `.fullAccess` on newer macOS.
    // rawValue 4 is write-only on newer macOS and is not enough for due-today reads.
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

let allCalendars = store.calendars(for: .reminder)

if listOnly {
    let titles = allCalendars.map { sanitize($0.title) }.filter { !$0.isEmpty }
    print(titles.joined(separator: "\n"))
    exit(0)
}

let calendars: [EKCalendar]
if let requestedListName {
    calendars = allCalendars.filter { $0.title == requestedListName }
    if calendars.isEmpty {
        fail("Missing reminder list: \(requestedListName)", code: 3)
    }
} else {
    calendars = allCalendars
}

let calendar = Calendar.current
let anchorDate: Date
if let requestedDateText {
    let parser = DateFormatter()
    parser.dateFormat = "yyyy-MM-dd"
    parser.locale = Locale(identifier: "en_US_POSIX")
    parser.timeZone = TimeZone.current
    guard let parsed = parser.date(from: requestedDateText) else {
        fail("Invalid date: \(requestedDateText); expected YYYY-MM-DD", code: 4)
    }
    anchorDate = parsed
} else {
    anchorDate = Date()
}

let start = calendar.startOfDay(for: anchorDate)
guard let end = calendar.date(byAdding: DateComponents(day: 1, second: -1), to: start) else {
    fail("Cannot calculate local day range", code: 4)
}

let predicate: NSPredicate
if requestedMode == "completed" {
    predicate = store.predicateForCompletedReminders(
        withCompletionDateStarting: start,
        ending: end,
        calendars: calendars
    )
} else {
    predicate = store.predicateForIncompleteReminders(
        withDueDateStarting: start,
        ending: end,
        calendars: calendars
    )
}

let semaphore = DispatchSemaphore(value: 0)
var rows: [String] = []

let formatter = DateFormatter()
formatter.dateFormat = "HH:mm"
formatter.locale = Locale(identifier: "en_US_POSIX")
formatter.timeZone = TimeZone.current

let completedFormatter = DateFormatter()
completedFormatter.dateFormat = "yyyy-MM-dd HH:mm"
completedFormatter.locale = Locale(identifier: "en_US_POSIX")
completedFormatter.timeZone = TimeZone.current

store.fetchReminders(matching: predicate) { reminders in
    for reminder in reminders ?? [] {
        let title = sanitize(reminder.title ?? "")
        let list = sanitize(reminder.calendar.title)
        let dueTime: String
        if let dueDate = reminder.dueDateComponents?.date {
            dueTime = formatter.string(from: dueDate)
        } else {
            dueTime = ""
        }
        if requestedMode == "completed" {
            let completedAt: String
            if let completionDate = reminder.completionDate {
                completedAt = completedFormatter.string(from: completionDate)
            } else {
                completedAt = ""
            }
            rows.append("\(title)\t\(dueTime)\t\(list)\t\(completedAt)")
        } else {
            rows.append("\(title)\t\(dueTime)\t\(list)")
        }
    }
    semaphore.signal()
}

if semaphore.wait(timeout: .now() + 15) == .timedOut {
    fail("EventKit fetchReminders timed out", code: 5)
}

print(rows.joined(separator: "\n"))
