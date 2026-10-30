#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p .build/host-checks
printf '%s\n' 'macOS AVFoundation synthesis-to-buffer only; no speaker/microphone/iOS device test.'
swiftc -parse-as-library Sources/EchoCore/*.swift App/SpeechController.swift HostChecks/SpeechBufferSmoke.swift -o .build/host-checks/speech-buffer-smoke
.build/host-checks/speech-buffer-smoke
