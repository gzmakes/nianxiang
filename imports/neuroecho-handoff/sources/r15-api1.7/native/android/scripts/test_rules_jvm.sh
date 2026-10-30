#!/bin/sh
# Isolated pure Rules.kt/RulesTest.kt execution. No Android plugin or SDK license.
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$#" -ne 1 ] || [ ! -x "$1/bin/java" ]; then
    echo "Usage: ./scripts/test_rules_jvm.sh /absolute/path/to/jdk17" >&2
    exit 2
fi
ECHO_JVM_CACHE=${ECHO_JVM_CACHE:-"$PROJECT_DIR/.gradle-user-home"}
exec env JAVA_HOME="$1" "$PROJECT_DIR/gradlew" --gradle-user-home "$ECHO_JVM_CACHE" --no-daemon --console=plain -p "$PROJECT_DIR/rules-jvm" test
