import SwiftUI

enum EchoPalette {
    static func color(_ hex: String) -> Color {
        let value = UInt64(hex.trimmingCharacters(in:CharacterSet(charactersIn:"#")),radix:16) ?? 0
        return Color(red:Double((value >> 16) & 255)/255,green:Double((value >> 8) & 255)/255,blue:Double(value & 255)/255)
    }
    static let ink = color(EchoSharedReference.color_ink)
    static let muted = color(EchoSharedReference.color_ink_mute)
    static let blue = color(EchoSharedReference.color_blob_blue)
    static let peach = color(EchoSharedReference.color_blob_peach)
}
struct EchoBackground: View {
    @Environment(\.accessibilityReduceMotion) private var systemReduce
    @AppStorage("echo.native.reduceMotion") private var reduceMotion = EchoSharedReference.defaultReduceMotion
    @AppStorage("echo.native.lightStrength") private var strength = EchoSharedReference.defaultLightIntensity
    @State private var drift = false
    var body: some View {
        let still = systemReduce || reduceMotion
        GeometryReader { geometry in
            ZStack {
                LinearGradient(colors: [EchoPalette.color(EchoSharedReference.color_bg_start), EchoPalette.color(EchoSharedReference.color_bg_mid), EchoPalette.color(EchoSharedReference.color_bg_end)], startPoint: .topLeading, endPoint: .bottomTrailing)
                Circle().fill(EchoPalette.blue.opacity(strength * 0.65)).frame(width:260,height:260).blur(radius:56).offset(x: -geometry.size.width * 0.3, y: still ? -220 : drift ? -190 : -240)
                Circle().fill(EchoPalette.peach.opacity(strength * 0.6)).frame(width:240,height:240).blur(radius:56).offset(x: geometry.size.width * 0.35, y: still ? 210 : drift ? 190 : 240)
            }.animation(still ? nil : .easeInOut(duration:18).repeatForever(autoreverses:true), value:drift).onAppear { drift = true }
        }.ignoresSafeArea().accessibilityHidden(true)
    }
}
struct EchoGlass: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @AppStorage("echo.native.reduceTransparency") private var userReduceTransparency = EchoSharedReference.defaultReduceTransparency
    @ViewBuilder func body(content: Content) -> some View {
        if reduceTransparency || userReduceTransparency { content.background(Color.white.opacity(0.94), in: Capsule()) }
        else {
            #if compiler(>=6.2)
            if #available(iOS 26.0, *) { content.glassEffect(.regular, in: Capsule()) }
            else { content.background(.ultraThinMaterial, in: Capsule()).overlay(Capsule().stroke(.white.opacity(0.8))) }
            #else
            content.background(.ultraThinMaterial, in: Capsule()).overlay(Capsule().stroke(.white.opacity(0.8)))
            #endif
        }
    }
}
extension View {
    @ViewBuilder func echoInlineNavigationTitle() -> some View {
        #if os(iOS)
        navigationBarTitleDisplayMode(.inline)
        #else
        self
        #endif
    }
    @ViewBuilder func echoURLInput() -> some View {
        #if os(iOS)
        textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
        #else
        autocorrectionDisabled()
        #endif
    }
    func echoGlass() -> some View { modifier(EchoGlass()) }
    func echoCard() -> some View {
        padding(20).frame(maxWidth:.infinity,alignment:.leading).background(.white.opacity(0.94),in:RoundedRectangle(cornerRadius:24)).overlay(RoundedRectangle(cornerRadius:24).stroke(.white.opacity(0.8)))
    }
}
struct EchoOrb: View {
    var size: CGFloat = 56
    @Environment(\.accessibilityReduceMotion) private var systemReduce
    @AppStorage("echo.native.reduceMotion") private var reduceMotion = EchoSharedReference.defaultReduceMotion
    @AppStorage("echo.native.lightStrength") private var strength = EchoSharedReference.defaultLightIntensity
    @State private var breath = false
    var body: some View {
        Circle().fill(LinearGradient(colors:[.white.opacity(0.9),EchoPalette.blue.opacity(strength),EchoPalette.peach.opacity(strength * 0.8)],startPoint:.topLeading,endPoint:.bottomTrailing))
            .overlay(Circle().stroke(.white.opacity(0.85),lineWidth:1.5)).overlay(alignment:.topLeading) { Ellipse().fill(.white.opacity(0.7)).frame(width:size*0.42,height:size*0.2).blur(radius:3).rotationEffect(.degrees(-30)).offset(x:size*0.12,y:size*0.12) }
            .shadow(color:EchoPalette.blue.opacity(strength*0.3),radius:18,y:8).frame(width:size,height:size)
            .scaleEffect(systemReduce || reduceMotion ? 1 : breath ? 1.035 : 0.97)
            .animation(systemReduce || reduceMotion ? nil : .easeInOut(duration:8).repeatForever(autoreverses:true),value:breath).onAppear { breath = true }
            .accessibilityLabel("安静陪着：淡蓝与淡杏的光")
    }
}
struct EchoPrimaryButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.body.weight(.semibold)).foregroundStyle(.white).frame(minHeight:44).frame(maxWidth:.infinity).padding(.horizontal,16).background(EchoPalette.ink.opacity(configuration.isPressed ? 0.8 : 1),in:Capsule())
    }
}
