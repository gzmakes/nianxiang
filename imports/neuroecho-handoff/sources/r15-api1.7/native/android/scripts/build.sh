#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
python3 scripts/sync_shared.py --check
python3 scripts/verify_project.py
ECHO_JAVA=java
if [ -n "${JAVA_HOME:-}" ]; then ECHO_JAVA="$JAVA_HOME/bin/java"; fi
if ! "$ECHO_JAVA" -version >/dev/null 2>&1; then
    echo "BUILD_NOT_RUN: JDK 17+ is missing. Install/select the Android Studio Gradle JDK; no APK was produced." >&2
    exit 2
fi
SDK_DIR=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}
if [ -z "$SDK_DIR" ] && [ -f local.properties ]; then
    SDK_DIR=$(sed -n 's/^sdk.dir=//p' local.properties)
fi
if [ -z "$SDK_DIR" ] || [ ! -f "$SDK_DIR/platforms/android-35/android.jar" ]; then
    echo "BUILD_NOT_RUN: Android SDK platform 35 is missing. Configure SDK in Android Studio/local.properties; no APK was produced." >&2
    exit 2
fi
./gradlew --no-daemon :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
echo "BUILD_OK: app/build/outputs/apk/debug/app-debug.apk"
