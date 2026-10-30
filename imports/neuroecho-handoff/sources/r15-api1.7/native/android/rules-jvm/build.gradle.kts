plugins { kotlin("jvm") version "2.1.20" }
kotlin {
    jvmToolchain(17)
    sourceSets {
        main { kotlin.srcDir("../app/src/main/java"); kotlin.include("cn/xinji/echo/UsabilityRules.kt", "cn/xinji/echo/ChangeUpdates.kt", "cn/xinji/echo/Connection.kt", "cn/xinji/echo/Rules.kt", "cn/xinji/echo/SourcePreview.kt", "cn/xinji/echo/Api.kt", "cn/xinji/echo/ProductRules.kt", "cn/xinji/echo/SourceRevocationRules.kt", "cn/xinji/echo/FollowupRules.kt", "cn/xinji/echo/CompanionBoundary.kt", "cn/xinji/echo/MoodRules.kt", "cn/xinji/echo/MoodOperation.kt", "cn/xinji/echo/ReadAloud.kt", "cn/xinji/echo/shared/EchoSharedReference.kt") }
        test { kotlin.srcDir("../app/src/test/java"); kotlin.include("cn/xinji/echo/UsabilityRulesTest.kt", "cn/xinji/echo/ChangeUpdatesTest.kt", "cn/xinji/echo/ConnectionTest.kt", "cn/xinji/echo/RulesTest.kt", "cn/xinji/echo/SourcePreviewTest.kt", "cn/xinji/echo/ApiMetadataTest.kt", "cn/xinji/echo/ProductRulesTest.kt", "cn/xinji/echo/SourceRevocationTest.kt", "cn/xinji/echo/FollowupRulesTest.kt", "cn/xinji/echo/CompanionBoundaryTest.kt", "cn/xinji/echo/MoodRulesTest.kt", "cn/xinji/echo/MoodOperationTest.kt", "cn/xinji/echo/ReadAloudTest.kt", "cn/xinji/echo/ApiContractTest.kt") }
    }
}
dependencies { implementation("org.json:json:20240303"); implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.0"); testImplementation("junit:junit:4.13.2") }
tasks.test { useJUnit(); testLogging { events("passed", "skipped", "failed") } }
