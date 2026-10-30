"""Preview retention checks use synthetic text and no external sources."""
import time

from server import main


def test_unconsumed_snapshots_are_removed_without_further_requests(monkeypatch):
    with main._preview_lock:
        if main._preview_timer:
            main._preview_timer.cancel()
        main._preview_timer = None
        main._source_previews.clear()
    monkeypatch.setattr(main, "_PREVIEW_TTL", 0.12)
    try:
        first = main._save_preview("lark:first", {"text": "fake preview 1"})
        time.sleep(0.05)
        second = main._save_preview("lark:second", {"text": "fake preview 2"})
        # No further cache reads/saves/consumption trigger cleanup.
        time.sleep(0.35)
        with main._preview_lock:
            assert first not in main._source_previews
            assert second not in main._source_previews
    finally:
        with main._preview_lock:
            if main._preview_timer:
                main._preview_timer.cancel()
            main._preview_timer = None
            main._source_previews.clear()
