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

struct AllDueRow: Encodable {
    let name: String
    let due_time: String
    let list: String
    let completed_at: String?
    let due_date: String
}

let args = Array(CommandLine.arguments.dropFirst())
let listOnly = args.count == 1 && args[0] == "--lists"
let requestedListName = args.first
let requestedDateText = args.dropFirst().first
let requestedMode = args.dropFirst(2).first ?? "incomplete"
let store = EKEventStore()

if !listOnly && requestedMode != "incomplete" && requestedMode != "completed" && requestedMode != "all-due" {
    fail("Invalid mode: \(requestedMode); expected incomplete, completed, or all-due", code: 4)
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
} else if requestedMode == "all-due" {
    predicate = store.predicateForReminders(in: calendars)
} else {
    predicate = store.predicateForIncompleteReminders(
        withDueDateStarting: start,
        ending: end,
        calendars: calendars
    )
}

let semaphore = DispatchSemaphore(value: 0)
var rows: [String] = []
var allDueRows: [AllDueRow] = []

let formatter = DateFormatter()
formatter.dateFormat = "HH:mm"
formatter.locale = Locale(identifier: "en_US_POSIX")
formatter.timeZone = TimeZone.current

let dueFormatter = DateFormatter()
dueFormatter.dateFormat = "yyyy-MM-dd HH:mm"
dueFormatter.locale = Locale(identifier: "en_US_POSIX")
dueFormatter.timeZone = TimeZone.current

let completedFormatter = DateFormatter()
completedFormatter.dateFormat = "yyyy-MM-dd HH:mm"
completedFormatter.locale = Locale(identifier: "en_US_POSIX")
completedFormatter.timeZone = TimeZone.current

store.fetchReminders(matching: predicate) { reminders in
    for reminder in reminders ?? [] {
        let title = requestedMode == "all-due" ? (reminder.title ?? "") : sanitize(reminder.title ?? "")
        let list = requestedMode == "all-due" ? reminder.calendar.title : sanitize(reminder.calendar.title)
        let dueDate = reminder.dueDateComponents?.date
        if requestedMode == "all-due" {
            guard let dueDate else {
                continue
            }
            if dueDate < start || dueDate > end {
                continue
            }
        }

        let dueTime = dueDate.map { formatter.string(from: $0) } ?? ""
        let dueAt = dueDate.map { dueFormatter.string(from: $0) } ?? ""
        if requestedMode == "all-due" {
            let completedAt = reminder.completionDate.map { completedFormatter.string(from: $0) }
            allDueRows.append(AllDueRow(
                name: title,
                due_time: dueTime,
                list: list,
                completed_at: completedAt,
                due_date: dueAt
            ))
        } else if requestedMode == "completed" {
            let completedAt: String
            if let completionDate = reminder.completionDate {
                completedAt = completedFormatter.string(from: completionDate)
            } else {
                completedAt = ""
            }
            rows.append("\(title)\t\(dueTime)\t\(list)\t\(completedAt)\t\(dueAt)")
        } else {
            rows.append("\(title)\t\(dueTime)\t\(list)\t\t\(dueAt)")
        }
    }
    semaphore.signal()
}

if semaphore.wait(timeout: .now() + 15) == .timedOut {
    fail("EventKit fetchReminders timed out", code: 5)
}

if requestedMode == "all-due" {
    do {
        let data = try JSONEncoder().encode(allDueRows)
        guard let output = String(data: data, encoding: .utf8) else {
            fail("Cannot encode EventKit all-due output", code: 6)
        }
        print(output)
    } catch {
        fail("Cannot encode EventKit all-due output: \(error)", code: 6)
    }
} else {
    print(rows.joined(separator: "\n"))
}
