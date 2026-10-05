import UserNotifications

/// macOS notifications: the "Meeting detected — take notes?" prompt with Start / Not now buttons,
/// plus plain info banners.
final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Notifier()
    private let center = UNUserNotificationCenter.current()

    func setup() {
        center.delegate = self
        let start = UNNotificationAction(identifier: "START", title: "Start Notes", options: [])
        let skip = UNNotificationAction(identifier: "SKIP", title: "Not now", options: [])
        center.setNotificationCategories([
            UNNotificationCategory(identifier: "MEETING", actions: [start, skip], intentIdentifiers: []),
        ])
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    func meetingDetected(in app: String) {
        let content = UNMutableNotificationContent()
        content.title = "Meeting detected in \(app)"
        content.body = "Take notes for this call?"
        content.categoryIdentifier = "MEETING"
        content.sound = .default
        center.add(UNNotificationRequest(identifier: "meeting", content: content, trigger: nil))
    }

    func clearMeetingPrompt() {
        center.removeDeliveredNotifications(withIdentifiers: ["meeting"])
    }

    func info(_ title: String, _ body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let action = response.actionIdentifier
        if response.notification.request.content.categoryIdentifier == "MEETING",
           action == "START" || action == UNNotificationDefaultActionIdentifier {
            Task { @MainActor in AppState.shared.startFromDetection() }
        }
        completionHandler()
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}
