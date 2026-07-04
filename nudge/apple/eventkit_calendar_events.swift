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

let store = EKEventStore()

func hasReadableEventAccess(_ status: EKAuthorizationStatus) -> Bool {
    // rawValue 3 is `.authorized` on older macOS and `.fullAccess` on newer macOS.
    // rawValue 4 is `.writeOnly` on newer macOS and is not enough for reads.
    return status.rawValue == 3
}

func requestEventAccessIfNeeded() -> Bool {
    let status = EKEventStore.authorizationStatus(for: .event)
    if hasReadableEventAccess(status) {
        return true
    }
    if status.rawValue != 0 {
        return false
    }

    let semaphore = DispatchSemaphore(value: 0)
    var granted = false
    var requestError = ""

    if #available(macOS 14.0, *) {
        store.requestFullAccessToEvents { ok, error in
            granted = ok
            if let error {
                requestError = String(describing: error)
            }
            semaphore.signal()
        }
    } else {
        store.requestAccess(to: .event) { ok, error in
            granted = ok
            if let error {
                requestError = String(describing: error)
            }
            semaphore.signal()
        }
    }

    if semaphore.wait(timeout: .now() + 15) == .timedOut {
        fail("EventKit Calendar access request timed out", code: 2)
    }
    if !requestError.isEmpty {
        fail("EventKit Calendar access request failed: \(requestError)", code: 2)
    }
    return granted
}

if CommandLine.arguments.count >= 2 && CommandLine.arguments[1] == "--lists" {
    if !requestEventAccessIfNeeded() {
        fail("EventKit Calendar full access denied or not readable", code: 2)
    }

    let names = store.calendars(for: .event)
        .map { sanitize($0.title) }
        .sorted()
    print(names.joined(separator: "\n"))
    exit(0)
}

if CommandLine.arguments.count < 3 {
    fail("Usage: eventkit_calendar_events.swift [--lists] | <start: yyyy-MM-dd HH:mm> <end: yyyy-MM-dd HH:mm> [calendar names...]")
}

let startText = CommandLine.arguments[1]
let endText = CommandLine.arguments[2]
let requestedCalendarNames = Array(CommandLine.arguments.dropFirst(3))

let formatter = DateFormatter()
formatter.locale = Locale(identifier: "en_US_POSIX")
formatter.dateFormat = "yyyy-MM-dd HH:mm"

guard let startDate = formatter.date(from: startText) else {
    fail("Invalid start date: \(startText)", code: 4)
}
guard let endDate = formatter.date(from: endText) else {
    fail("Invalid end date: \(endText)", code: 4)
}

if !requestEventAccessIfNeeded() {
    fail("EventKit Calendar full access denied or not readable", code: 2)
}

let allCalendars = store.calendars(for: .event)
let calendars: [EKCalendar]
if requestedCalendarNames.isEmpty {
    calendars = allCalendars
} else {
    let requestedSet = Set(requestedCalendarNames)
    calendars = allCalendars.filter { requestedSet.contains($0.title) }
    let foundNames = Set(calendars.map { $0.title })
    let missing = requestedCalendarNames.filter { !foundNames.contains($0) }
    if !missing.isEmpty {
        fail("Missing calendars: \(missing.joined(separator: ", "))", code: 3)
    }
}

let predicate = store.predicateForEvents(
    withStart: startDate,
    end: endDate,
    calendars: calendars
)

let rows = store.events(matching: predicate)
    .sorted {
        if $0.startDate == $1.startDate {
            return ($0.title ?? "") < ($1.title ?? "")
        }
        return $0.startDate < $1.startDate
    }
    .map { event in
        let title = sanitize(event.title ?? "")
        let start = formatter.string(from: event.startDate)
        let end = formatter.string(from: event.endDate)
        let calendarName = sanitize(event.calendar.title)
        return "\(title)\t\(start)\t\(end)\t\(calendarName)"
    }

print(rows.joined(separator: "\n"))
