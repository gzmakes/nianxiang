#!/usr/bin/env python3
"""Generate the app-only Xcode project. Core checks run separately through SwiftPM."""
from pathlib import Path
from hashlib import sha256
import json

ROOT = Path(__file__).resolve().parent
uid = lambda key: sha256(key.encode()).hexdigest()[:24].upper()
quote = lambda value: json.dumps(str(value), ensure_ascii=False)
objects = []
def add(key, body):
    objects.append(f'\t\t{uid(key)} = {{ {body} }};')
    return uid(key)

def files(group, directory):
    result = []
    for path in sorted((ROOT / directory).glob('*.swift')):
        relative = str(path.relative_to(ROOT))
        add('file:' + relative, f'isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {quote(path.name)}; sourceTree = "<group>";')
        add('build:' + relative, f'isa = PBXBuildFile; fileRef = {uid("file:" + relative)};')
        result.append(relative)
    return result
app = files('app', 'App')
core = files('core', 'Sources/EchoCore')
add('plist', 'isa = PBXFileReference; lastKnownFileType = text.plist.xml; path = Info.plist; sourceTree = "<group>";')
add('assets', 'isa = PBXFileReference; lastKnownFileType = folder.assetcatalog; path = Assets.xcassets; sourceTree = "<group>";')
add('assets-build', f'isa = PBXBuildFile; fileRef = {uid("assets")};')
add('product', 'isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = Echo.app; sourceTree = BUILT_PRODUCTS_DIR;')
add('appgroup', f'isa = PBXGroup; path = App; sourceTree = "<group>"; children = (' + ','.join(uid('file:' + p) for p in app) + f',{uid("plist")},{uid("assets")});')
add('coregroup', 'isa = PBXGroup; name = EchoCore; path = Sources/EchoCore; sourceTree = "<group>"; children = (' + ','.join(uid('file:' + p) for p in core) + ');')
add('productgroup', f'isa = PBXGroup; name = Products; sourceTree = "<group>"; children = ({uid("product")});')
add('rootgroup', f'isa = PBXGroup; sourceTree = "<group>"; children = ({uid("appgroup")},{uid("coregroup")},{uid("productgroup")});')
add('sources', 'isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; runOnlyForDeploymentPostprocessing = 0; files = (' + ','.join(uid('build:' + p) for p in app + core) + ');')
add('frameworks', 'isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; runOnlyForDeploymentPostprocessing = 0; files = ();')
add('resources', f'isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; runOnlyForDeploymentPostprocessing = 0; files = ({uid("assets-build")});')
for config in ['Debug', 'Release']:
    common = {'IPHONEOS_DEPLOYMENT_TARGET':'17.0','SDKROOT':'iphoneos','CLANG_ENABLE_MODULES':'YES','SWIFT_VERSION':'5.0'}
    appsettings = {**common,'PRODUCT_BUNDLE_IDENTIFIER':'com.xinji.echo','PRODUCT_NAME':'$(TARGET_NAME)','INFOPLIST_FILE':'App/Info.plist','GENERATE_INFOPLIST_FILE':'NO','CODE_SIGN_STYLE':'Automatic','TARGETED_DEVICE_FAMILY':'1,2','SUPPORTED_PLATFORMS':'iphoneos iphonesimulator','SUPPORTS_MACCATALYST':'NO','ENABLE_PREVIEWS':'YES','SWIFT_STRICT_CONCURRENCY':'targeted'}
    if config == 'Debug': appsettings.update(SWIFT_OPTIMIZATION_LEVEL='-Onone',SWIFT_ACTIVE_COMPILATION_CONDITIONS='DEBUG')
    else: appsettings['SWIFT_OPTIMIZATION_LEVEL'] = '-O'
    def settings(values): return ' '.join(quote(k) + ' = ' + quote(v) + ';' for k, v in values.items())
    add('project-' + config, f'isa = XCBuildConfiguration; name = {config}; buildSettings = {{ {settings(common)} }};')
    add('app-' + config, f'isa = XCBuildConfiguration; name = {config}; buildSettings = {{ {settings(appsettings)} }};')
for owner in ['project', 'app']:
    add(owner + '-configs', f'isa = XCConfigurationList; defaultConfigurationIsVisible = 0; defaultConfigurationName = Release; buildConfigurations = ({uid(owner + "-Debug")},{uid(owner + "-Release")});')
add('target', f'isa = PBXNativeTarget; buildConfigurationList = {uid("app-configs")}; buildPhases = ({uid("sources")},{uid("frameworks")},{uid("resources")}); buildRules = (); dependencies = (); name = Echo; productName = Echo; productReference = {uid("product")}; productType = "com.apple.product-type.application";')
add('project', f'isa = PBXProject; attributes = {{ LastUpgradeCheck = 2600; TargetAttributes = {{ {uid("target")} = {{ CreatedOnToolsVersion = 26.0; }}; }}; }}; buildConfigurationList = {uid("project-configs")}; compatibilityVersion = "Xcode 15.0"; developmentRegion = zh-Hans; hasScannedForEncodings = 0; knownRegions = (en,"zh-Hans",Base); mainGroup = {uid("rootgroup")}; productRefGroup = {uid("productgroup")}; projectDirPath = ""; projectRoot = ""; targets = ({uid("target")});')
project = ROOT / 'Echo.xcodeproj'
project.mkdir(exist_ok=True)
(project / 'project.pbxproj').write_text('// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {};\n\tobjectVersion = 60;\n\tobjects = {\n' + '\n'.join(objects) + '\n\t};\n\trootObject = ' + uid('project') + ';\n}\n')
scheme = project / 'xcshareddata/xcschemes/Echo.xcscheme'
scheme.parent.mkdir(parents=True, exist_ok=True)
ref = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{uid("target")}" BuildableName="Echo.app" BlueprintName="Echo" ReferencedContainer="container:Echo.xcodeproj"/>'
scheme.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="2600" version="1.7">
<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{ref}</BuildActionEntry></BuildActionEntries></BuildAction>
<TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES"><Testables/></TestAction>
<LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable></LaunchAction>
<ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable></ProfileAction>
<AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>''')
print(f'Generated {len(app) + len(core)} app source references and a shared Echo scheme.')
