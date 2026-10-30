#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 sync_shared.py --check
mkdir -p .build/host-checks
printf '%s\n' 'Host macOS SwiftUI typecheck only; iOS SDK / UIKit / device layout are not validated.'
swiftc -typecheck App/*.swift Sources/EchoCore/*.swift
swiftc -parse-as-library Sources/EchoCore/*.swift App/DeviceCredentialStore.swift App/EchoStore.swift HostChecks/StoreLifecycleChecks.swift -o .build/host-checks/store-lifecycle
.build/host-checks/store-lifecycle
swiftc -parse-as-library Sources/EchoCore/*.swift App/DeviceCredentialStore.swift App/EchoStore.swift App/SharedDesign.generated.swift App/MoodStore.swift HostChecks/MoodLifecycleChecks.swift -o .build/host-checks/mood-lifecycle
.build/host-checks/mood-lifecycle
swiftc -parse-as-library Sources/EchoCore/*.swift App/DeviceCredentialStore.swift App/EchoStore.swift App/SharedDesign.generated.swift App/MoodStore.swift HostChecks/MoodLedgerLifecycleChecks.swift -o .build/host-checks/mood-ledger-lifecycle
.build/host-checks/mood-ledger-lifecycle
swiftc -parse-as-library Sources/EchoCore/*.swift App/SpeechController.swift HostChecks/SpeechLifecycleChecks.swift -o .build/host-checks/speech-lifecycle
.build/host-checks/speech-lifecycle

swiftc -parse-as-library Sources/EchoCore/*.swift App/DeviceCredentialStore.swift App/EchoStore.swift HostChecks/DeviceConnectionLifecycleChecks.swift -o .build/host-checks/device-connection-lifecycle
.build/host-checks/device-connection-lifecycle

swiftc -parse-as-library Sources/EchoCore/*.swift App/DeviceCredentialStore.swift App/EchoStore.swift HostChecks/ChangeRefreshLifecycleChecks.swift -o .build/host-checks/change-refresh-lifecycle
.build/host-checks/change-refresh-lifecycle
