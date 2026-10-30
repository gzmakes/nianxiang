import Foundation

public struct EchoCompanionBoundary: Codable, Sendable {
    public let revision: Int
    public let mode: String
    public let until: String?
    public let timeZone: String
    public let suppressionRevision: Int
    public var hasKnownMode: Bool {["active","paused","until"].contains(mode)}
    public var label: String {
        switch mode {case "active":return "可以按约定范围联系";case "paused":return "主动联系已暂停";case "until":return "主动联系暂停至约定时间";default:return "边界状态待核对"}
    }
    public static func nextMidnight(timeZone: String, now: Date = Date()) throws -> Date {
        guard let zone=TimeZone(identifier:timeZone) else {throw EchoAPIError.message("请填写有效时区。")}
        var calendar=Calendar(identifier:.gregorian); calendar.timeZone=zone
        guard let next=calendar.date(byAdding:.day,value:1,to:calendar.startOfDay(for:now)) else {throw EchoAPIError.message("暂时无法确定当地下一午夜。")}
        return next
    }
}
