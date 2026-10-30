import Foundation
import CryptoKit

/// A dated self-report, never a diagnosis, a device measurement or automatic memory.
public struct EchoMood: Codable, Equatable, Identifiable, Sendable {
    public let date: String
    public let x: Double
    public let y: Double
    public let note: String
    public let updatedAt: String
    public var id: String {date}
    public var isValid: Bool {Self.validDay(date) && x.isFinite && y.isFinite && (-1...1).contains(x) && (-1...1).contains(y) && note.unicodeScalars.count <= 1000 && EchoFollowup.parse(updatedAt) != nil}
    public static func validDay(_ value: String) -> Bool {
        guard value.range(of:#"^\d{4}-\d{2}-\d{2}$"#,options:.regularExpression) != nil else {return false}
        let f=DateFormatter();f.calendar=Calendar(identifier:.gregorian);f.locale=Locale(identifier:"en_US_POSIX");f.timeZone=TimeZone(secondsFromGMT:0);f.dateFormat="yyyy-MM-dd";f.isLenient=false
        return f.date(from:value).map {f.string(from:$0) == value} ?? false
    }
    public static func day(_ date: Date = Date(), zone: TimeZone = .current) -> String {
        let f=DateFormatter();f.calendar=Calendar(identifier:.gregorian);f.locale=Locale(identifier:"en_US_POSIX");f.timeZone=zone;f.dateFormat="yyyy-MM-dd";return f.string(from:date)
    }
    public var chatDraft: String {
        let feeling=x < -0.05 ? "有些不愉快" : x > 0.05 ? "有些愉快" : "感受在中间"
        let energy=y < -0.05 ? "精力偏低" : y > 0.05 ? "精力偏高" : "精力在中间"
        return "我想聊聊自己为 \(date) 留下的感受：\(feeling)，\(energy)。" + (note.isEmpty ? "" : "\n我写下的是：\(note)") + "\n这是我自己记录的感受，不是设备识别，也不代表一整天。"
    }
}

public struct EchoMoodMutation: Codable, Equatable, Sendable {
    public enum Kind: String, Codable, Sendable {case save, delete}
    public let localID: UUID
    public let kind: Kind
    public let day: String
    public let x: Double
    public let y: Double
    public let note: String
    public let expectedUpdatedAt: String?
    /// Absent on R10 pending writes. Never add these to an existing legacy write.
    public let requestID: String?
    public let operationJSON: String?
    public init(kind: Kind, draft: EchoMoodDraft) {
        localID=UUID();self.kind=kind;day=draft.day;x=draft.x;y=draft.y;note=draft.note;expectedUpdatedAt=draft.expectedUpdatedAt
        requestID=nil;operationJSON=nil
    }
    private init(copy: Self, requestID: String, operationJSON: String) {
        localID=copy.localID;kind=copy.kind;day=copy.day;x=copy.x;y=copy.y;note=copy.note;expectedUpdatedAt=copy.expectedUpdatedAt
        self.requestID=requestID;self.operationJSON=operationJSON
    }
    /// Called only for a new user-confirmed mutation, never while restoring/retrying.
    public func preparedForLedger() throws -> Self {
        guard requestID == nil, operationJSON == nil, EchoMood.validDay(day), expectedUpdatedAt == nil || EchoFollowup.parse(expectedUpdatedAt) != nil else {throw EchoAPIError.message("原请求不可重新编号，请先核对。")}
        var body: [String:Any]=["kind":kind.rawValue,"date":day,"expected_updated_at":expectedUpdatedAt as Any? ?? NSNull()]
        if kind == .save {
            guard x.isFinite,y.isFinite,(-1...1).contains(x),(-1...1).contains(y),note.unicodeScalars.count <= 1000 else {throw EchoAPIError.message("请核对位置与文字。")}
            body["x"]=x;body["y"]=y;body["note"]=note
        } else {guard expectedUpdatedAt != nil else {throw EchoAPIError.message("先读取已保存版本再删除。")}}
        let data=try JSONSerialization.data(withJSONObject:body,options:[.sortedKeys])
        guard let raw=String(data:data,encoding:.utf8) else {throw EchoAPIError.message("原请求无法保存，尚未发送。")}
        return Self(copy:self,requestID:UUID().uuidString,operationJSON:raw)
    }
    public var hasLedgerIdentity: Bool {requestID != nil || operationJSON != nil}
    public var operationHash: String? {operationJSON.map {SHA256.hash(data:Data($0.utf8)).map {String(format:"%02x",$0)}.joined()}}
    public var validLedgerIdentity: Bool {
        guard let requestID, UUID(uuidString:requestID) != nil,let operationJSON,
              operationJSON.count <= 16384, let data=operationJSON.data(using:.utf8),data.count <= 16384,let object=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any],
              object["kind"] as? String == kind.rawValue,object["date"] as? String == day,object.keys.contains("expected_updated_at"),
              (object["expected_updated_at"] as? String) == expectedUpdatedAt else {return false}
        let expectedKeys: Set<String>=kind == .save ? ["kind","date","expected_updated_at","x","y","note"] : ["kind","date","expected_updated_at"]
        guard Set(object.keys) == expectedKeys else {return false}
        if expectedUpdatedAt == nil && !(object["expected_updated_at"] is NSNull) {return false}
        if kind == .save {
            struct Numbers: Decodable {let x:Double;let y:Double;let note:String}
            guard let values=try? JSONDecoder().decode(Numbers.self,from:data), values.x == x,values.y == y,values.note == note,x.isFinite,y.isFinite,(-1...1).contains(x),(-1...1).contains(y),note.unicodeScalars.count <= 1000 else {return false}
        }
        return EchoMood.validDay(day) && (expectedUpdatedAt == nil || EchoFollowup.parse(expectedUpdatedAt) != nil) && (kind != .delete || expectedUpdatedAt != nil)
    }
    public func matches(_ item: EchoMood) -> Bool {item.isValid && item.date == day && item.x == x && item.y == y && item.note == note && item.updatedAt != expectedUpdatedAt}
}

public struct EchoMoodDraft: Codable, Equatable, Sendable {
    public let origin: String
    public let sessionID: String
    public let day: String
    public var x=0.0
    public var y=0.0
    public var xSelected=false
    public var ySelected=false
    public var note=""
    public var expectedUpdatedAt: String?
    public var dirty=false
    public var needsReview=false
    public var pending: EchoMoodMutation?
    /// Observed ledger status only; it never changes the immutable operation JSON.
    public var operationState: String?
    /// Persisted before metadata cancellation. Never apply this identity again.
    public var cancelRequested: Bool?
    public init(origin: String, sessionID: String, day: String, record: EchoMood? = nil) {
        self.origin=origin;self.sessionID=sessionID;self.day=day
        if let record {x=record.x;y=record.y;note=record.note;expectedUpdatedAt=record.updatedAt;xSelected=true;ySelected=true}
    }
    public var canSave: Bool {Self.valid(self) && xSelected && ySelected && dirty && pending == nil && !needsReview}
    private static func valid(_ d: Self) -> Bool {EchoMood.validDay(d.day) && d.x.isFinite && d.y.isFinite && (-1...1).contains(d.x) && (-1...1).contains(d.y) && d.note.unicodeScalars.count <= 1000}
}
