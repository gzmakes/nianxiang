import Foundation

/// Citations are evidence returned with a reply, never new memories or account grants.
public enum EchoMessageCitation: Codable, Equatable, Sendable {
    case memory(id: String, version: Int, text: String)
    case feishuDocument(EchoFeishuDocumentCitation)
    case unsupported

    private enum CodingKeys: String, CodingKey { case kind, id, version, title, url, text }
    public init(from decoder: Decoder) throws {
        guard let value = try? decoder.container(keyedBy:CodingKeys.self) else {self = .unsupported; return}
        if value.contains(.kind) {
            guard (try? value.decode(String.self,forKey:.kind)) == "feishu_document",
                  let title = try? value.decode(String.self,forKey:.title),
                  let url = try? value.decode(String.self,forKey:.url),
                  let text = try? value.decode(String.self,forKey:.text) else {self = .unsupported; return}
            let document = EchoFeishuDocumentCitation(title:title,url:url,text:text)
            self = document.isValid ? .feishuDocument(document) : .unsupported
        } else if let id = try? value.decode(String.self,forKey:.id), !id.isEmpty,
                  let version = try? value.decode(Int.self,forKey:.version), version > 0,
                  let text = try? value.decode(String.self,forKey:.text) {
            self = .memory(id:id,version:version,text:text)
        } else {self = .unsupported}
    }
    public func encode(to encoder: Encoder) throws {
        var value = encoder.container(keyedBy:CodingKeys.self)
        switch self {
        case .memory(let id,let version,let text):
            try value.encode(id,forKey:.id); try value.encode(version,forKey:.version); try value.encode(text,forKey:.text)
        case .feishuDocument(let document):
            try value.encode("feishu_document",forKey:.kind); try value.encode(document.title,forKey:.title)
            try value.encode(document.url,forKey:.url); try value.encode(document.text,forKey:.text)
        case .unsupported: break
        }
    }
}

public struct EchoFeishuDocumentCitation: Equatable, Sendable {
    public let title: String
    public let url: String
    public let text: String
    public init(title: String, url: String, text: String) {self.title=title; self.url=url; self.text=text}
    public var isValid: Bool {
        !title.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && title.unicodeScalars.count <= 500 && safeURL != nil
    }
    public var safeURL: URL? {EchoFeishuCitationURL.validated(url)}
}

public enum EchoFeishuCitationURL {
    /// Match the raw authority and encoded path before URL normalization.
    /// The result is only for an explicit OS-browser open, never an EchoAPI request.
    public static func validated(_ raw: String) -> URL? {
        guard !raw.isEmpty, raw.utf8.count <= 4096,
              raw == raw.trimmingCharacters(in:.whitespacesAndNewlines),
              !raw.contains("\\"), !raw.unicodeScalars.contains(where:{CharacterSet.whitespacesAndNewlines.contains($0) || $0.value <= 0x20 || (0x7f...0x9f).contains($0.value)}),
              raw.range(of:#"%(?:0[0-9a-f]|1[0-9a-f]|5c|7f)|%c2%(?:8[0-9a-f]|9[0-9a-f])"#,options:[.regularExpression,.caseInsensitive]) == nil,
              raw.range(of:#"^https://(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*(?:feishu\.cn|larksuite\.com)(?::443)?/"#,options:[.regularExpression,.caseInsensitive]) != nil,
              let parts = URLComponents(string:raw), parts.scheme?.lowercased() == "https",
              let host=parts.host, host.utf8.count <= 253,
              parts.user == nil, parts.password == nil, parts.port == nil || parts.port == 443,
              parts.percentEncodedPath.range(of:#"^/(?:docx|docs|wiki)/[A-Za-z0-9_-]+/?$"#,options:.regularExpression) != nil,
              let url = parts.url else {return nil}
        return url
    }
}

public extension EchoMessage {
    var documentCitations: [EchoFeishuDocumentCitation] {
        guard role == "assistant", deliveryPending != true,
              displayParts.contains(where:{!$0.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty}) else {return []}
        return citations.compactMap {if case .feishuDocument(let document) = $0, document.isValid {return document}; return nil}
    }
}

/// Keep a rendered button bound to the same identity and exact visible reply.
public struct EchoDocumentCitationTarget: Sendable {
    private let origin: String
    private let sessionID: String
    private let messageID: String
    private let messageText: String
    private let visibleParts: [String]
    private let document: EchoFeishuDocumentCitation
    public init?(message: EchoMessage, document: EchoFeishuDocumentCitation, origin: String, sessionID: String?) {
        guard let sessionID, !sessionID.isEmpty, !origin.isEmpty, !message.id.isEmpty,
              message.documentCitations.contains(document) else {return nil}
        self.origin=origin; self.sessionID=sessionID; messageID=message.id
        messageText=message.text; visibleParts=message.displayParts; self.document=document
    }
    public func resolvedURL(origin: String, sessionID: String?, messages: [EchoMessage]) -> URL? {
        let matches = messages.filter {$0.id == messageID}
        guard self.origin == origin, self.sessionID == sessionID, matches.count == 1,
              let current = matches.first, current.text == messageText,
              current.displayParts == visibleParts, current.documentCitations.contains(document) else {return nil}
        return document.safeURL
    }
}
