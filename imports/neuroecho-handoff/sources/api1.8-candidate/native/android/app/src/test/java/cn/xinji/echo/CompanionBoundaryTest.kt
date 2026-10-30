package cn.xinji.echo

import java.time.Instant
import java.time.ZoneId
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CompanionBoundaryTest {
    private fun fixture() = JSONObject("""{"revision":3,"mode":"active","until":null,"time_zone":"Asia/Shanghai","suppression_revision":2}""")
    @Test fun strictBoundaryRejectsUnknownIncompleteAndMalformedReceipts() {
        val good = companionBoundary(fixture())
        assertEquals(3, good.revision); assertFalse(good.isPaused)
        for (bad in listOf(fixture().put("mode", "unknown"), fixture().put("revision", -1),
            fixture().put("time_zone", "Bad/Zone"), fixture().put("mode", "until"),
            fixture().put("until", "2026-10-31T00:00:00Z"))) assertThrows(IllegalArgumentException::class.java) { companionBoundary(bad) }
        val missing = fixture().apply { remove("suppression_revision") }
        assertThrows(IllegalArgumentException::class.java) { companionBoundary(missing) }
    }
    @Test fun todayStopsAtDeviceLocalMidnightAndCarriesExpectedRevision() {
        val now = Instant.parse("2026-10-30T02:00:00Z")
        val change = boundaryChange("s", companionBoundary(fixture()), "until", now, ZoneId.of("Asia/Shanghai"))
        assertEquals("2026-10-30T16:00:00Z", change.until)
        assertEquals(3, change.body().getInt("expected_revision")); assertTrue(change.body().getBoolean("confirmed"))
        assertEquals("Asia/Shanghai", change.body().getString("time_zone"))
        assertTrue(change.matches(CompanionBoundary(4, "until", change.until, "Asia/Shanghai", 3)))
        assertFalse(change.matches(CompanionBoundary(3, "until", change.until, "Asia/Shanghai", 3)))
        assertFalse(change.matches(CompanionBoundary(4, "paused", null, "Asia/Shanghai", 3)))
    }
    @Test fun localMidnightUsesCalendarRatherThanFixed24HoursAcrossDst() {
        val current = companionBoundary(fixture())
        val now = Instant.parse("2026-03-08T06:30:00Z")
        val change = boundaryChange("s", current, "until", now, ZoneId.of("America/New_York"))
        assertEquals("2026-03-09T04:00:00Z", change.until)
    }
    @Test fun newChatFreezesTimezoneButOldPendingBodyStaysUnchanged() {
        val fresh = PendingTurn.new("s", "今天先别问", timeZone = "Asia/Shanghai")
        assertEquals("Asia/Shanghai", fresh.body().getString("time_zone"))
        assertEquals(fresh, PendingTurn.decode(fresh.encode()))
        val old = PendingTurn.decode("""{"id":"old","session_id":"s","text":"今天先别问","cancel":false}""")!!
        assertFalse(old.body().has("time_zone")); assertFalse(JSONObject(old.encode()).has("time_zone"))
    }
}
