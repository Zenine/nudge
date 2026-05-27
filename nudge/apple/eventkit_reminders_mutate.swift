import EventKit
import Foundation

func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

if CommandLine.arguments.count < 4 {
    fail("Usage: eventkit_reminders_mutate.swift <create|complete|complete-id|delete|set-id> <list-name> <title-or-external-id> [due-date YYYY-MM-DD HH:mm] [priority] [remind-date YYYY-MM-DD HH:mm] [external-id] [notes]")
}

let operation = CommandLine.arguments[1]
let listName = CommandLine.arguments[2]
let title = CommandLine.arguments[3]
let dueDateText = CommandLine.arguments.count >= 5 ? CommandLine.arguments[4] : ""
let priorityText = CommandLine.arguments.count >= 6 ? CommandLine.arguments[5] : "0"
let remindDateText = CommandLine.arguments.count >= 7 ? CommandLine.arguments[6] : ""
let externalIdText = CommandLine.arguments.count >= 8 ? CommandLine.arguments[7] : ""
let notesText = CommandLine.arguments.count >= 9 ? CommandLine.arguments[8] : ""

if operation != "create" && operation != "complete" && operation != "complete-id" && operation != "delete" && operation != "set-id" {
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

func dateFromLocalMinute(_ value: String) -> Date? {
    if value.isEmpty {
        return nil
    }
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = TimeZone.current
    formatter.dateFormat = "yyyy-MM-dd HH:mm"
    guard let date = formatter.date(from: String(value.prefix(16))) else {
        fail("Invalid remind-date; expected YYYY-MM-DD HH:mm: \(value)", code: 6)
    }
    return date
}

if operation == "create" {
    guard let calendar = calendars.first else {
        fail("Missing reminder list: \(listName)", code: 3)
    }
    guard let dueComponents = parseLocalMinute(dueDateText) else {
        fail("create requires due-date YYYY-MM-DD HH:mm", code: 6)
    }
    let reminder = EKReminder(eventStore: store)
    reminder.calendar = calendar
    reminder.title = title
    reminder.dueDateComponents = dueComponents
    reminder.notes = notesText.isEmpty ? nil : notesText
    if let priority = Int(priorityText), priority > 0 {
        reminder.priority = priority
    }
    if let url = URL(string: externalIdText), !externalIdText.isEmpty {
        reminder.url = url
    }
    if let remindDate = dateFromLocalMinute(remindDateText) {
        reminder.addAlarm(EKAlarm(absoluteDate: remindDate))
    }
    do {
        try store.save(reminder, commit: true)
    } catch {
        fail("EventKit create failed: \(error)", code: 5)
    }
    print(externalIdText.isEmpty ? "created" : externalIdText)
    exit(0)
}

func fetchReminders(_ predicate: NSPredicate, timeoutMessage: String) -> [EKReminder] {
    let semaphore = DispatchSemaphore(value: 0)
    var fetched: [EKReminder] = []
    store.fetchReminders(matching: predicate) { reminders in
        fetched = reminders ?? []
        semaphore.signal()
    }
    if semaphore.wait(timeout: .now() + 15) == .timedOut {
        fail(timeoutMessage, code: 4)
    }
    return fetched
}

let dueComponents = parseLocalMinute(dueDateText)
let lookupExternalId = externalIdText.isEmpty ? title : externalIdText

var fetched = fetchReminders(
    store.predicateForReminders(in: calendars),
    timeoutMessage: "EventKit fetchReminders timed out"
)

if operation == "set-id", let dueDate = dateFromLocalMinute(dueDateText) {
    let start = Calendar.current.startOfDay(for: dueDate)
    guard let end = Calendar.current.date(byAdding: DateComponents(day: 2, second: -1), to: start) else {
        fail("Cannot calculate completed reminder lookup range", code: 4)
    }
    let completedPredicate = store.predicateForCompletedReminders(
        withCompletionDateStarting: start,
        ending: end,
        calendars: calendars
    )
    fetched.append(contentsOf: fetchReminders(
        completedPredicate,
        timeoutMessage: "EventKit fetchCompletedReminders timed out"
    ))
    var seenIdentifiers = Set<String>()
    fetched = fetched.filter { reminder in
        let identifier = reminder.calendarItemIdentifier
        if seenIdentifiers.contains(identifier) {
            return false
        }
        seenIdentifiers.insert(identifier)
        return true
    }
}

func reminderMatchesDueDate(_ reminder: EKReminder) -> Bool {
    guard let dueComponents else {
        return true
    }
    guard let reminderDue = reminder.dueDateComponents else {
        return false
    }
    if reminderDue.hour != dueComponents.hour || reminderDue.minute != dueComponents.minute {
        return false
    }
    if let year = reminderDue.year, year != dueComponents.year {
        return false
    }
    if let month = reminderDue.month, month != dueComponents.month {
        return false
    }
    if let day = reminderDue.day, day != dueComponents.day {
        return false
    }
    return true
}

let matches = fetched.filter { reminder in
    if operation == "complete-id" {
        if reminder.isCompleted {
            return false
        }
        if reminder.url?.absoluteString == lookupExternalId {
            return true
        }
        if let notes = reminder.notes {
            return notes.contains("Nudge-ID: \(lookupExternalId)")
        }
        return false
    }
    if reminder.title != title {
        return false
    }
    if !reminderMatchesDueDate(reminder) {
        return false
    }
    if operation == "complete" {
        return !reminder.isCompleted
    }
    if operation == "set-id" {
        return true
    }
    return true
}

if (dueComponents != nil || operation == "complete-id" || operation == "set-id") && matches.count != 1 {
    fail("Precise reminder match expected 1, found \(matches.count)", code: 7)
}

var changed = 0
for reminder in matches {
    do {
        if operation == "complete" {
            reminder.isCompleted = true
            try store.save(reminder, commit: true)
        } else if operation == "set-id" {
            if let url = URL(string: lookupExternalId), !lookupExternalId.isEmpty {
                reminder.url = url
            }
            let marker = "Nudge-ID: \(lookupExternalId)"
            if let notes = reminder.notes, !notes.isEmpty {
                if !notes.contains(marker) {
                    reminder.notes = notes + "\n\n" + marker
                }
            } else {
                reminder.notes = marker
            }
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
