#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 sync_shared.py
python3 generate_project.py
plutil -lint App/Info.plist Echo.xcodeproj/project.pbxproj
printf '%s\n' 'Checking Swift syntax only; this does not compile the iOS app.'
swiftc -frontend -parse App/*.swift Sources/EchoCore/*.swift
printf '%s\n' 'Compiling and running Foundation contract checks on the host; no account or network access.'
swift run --scratch-path .build EchoCoreChecks
