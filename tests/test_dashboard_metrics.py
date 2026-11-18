"""Dashboard insights read data/analytics.db and count each video once (latest snapshot)."""
import time

from engine import analytics, dashboard


def test_metrics_latest_snapshot(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    conn = analytics.connect(tmp_path / "data" / "analytics.db")
    now = time.time()
    for h, v in ((2, 100), (48, 900)):                       # same video, two snapshots
        analytics.record(conn, item_id="v1", channel="unsolved_after_dark", platform="youtube", hours_after=h,
                         views=v, stayed_pct=60, avg_pct_viewed=75, subs_gained=5, posted_at=now - 3600, hook="Hook A")
    analytics.record(conn, item_id="v2", channel="unsolved_after_dark", platform="instagram", hours_after=48,
                     views=300, stayed_pct=80, posted_at=now - 30 * 86400, hook="Hook B")
    conn.close()
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    from engine import stats_fetch
    monkeypatch.setattr(stats_fetch, "LIVE", tmp_path / "live.json")       # no live counters in this test
    m = dashboard._metrics()["unsolved_after_dark"]
    assert m["videos"] == 2 and m["views"] == 1200 and m["views_7d"] == 900
    assert m["best"] == ("Hook A", 900) and m["yt"] == 1 and m["ig"] == 1 and m["stayed"] == 70.0
    assert "hooks" not in dashboard._insight(m)              # 70% stayed = at the benchmark
    assert "hooks" in dashboard._insight({**m, "stayed": 50})


def test_stats_fetch_buckets_and_record(tmp_path, monkeypatch):
    import json as _json

    from engine import stats_fetch
    assert stats_fetch.due_bucket(1) is None and stats_fetch.due_bucket(30) == 24
    assert stats_fetch.due_bucket(100) == 48 and stats_fetch.due_bucket(200) == 192
    log = tmp_path / "publish_log.jsonl"
    rows = [{"at": time.time() - 30 * 3600, "platform": "youtube", "channel": "clutch_tales", "item_id": "it1",
             "what": "upload video.mp4 (private, scheduled)", "when": "", "details": {"title": "T1"}, "done": True,
             "result": {"video_id": "abc"}},
            {"at": time.time() - 30 * 3600, "platform": "youtube", "channel": "clutch_tales", "item_id": "dry",
             "what": "upload x", "details": {"dry_run": True}, "done": True, "result": {"video_id": "zzz"}}]
    log.write_text("\n".join(_json.dumps(r) for r in rows), encoding="utf-8")
    monkeypatch.setattr(stats_fetch, "LOG", log)
    monkeypatch.setattr(stats_fetch, "_youtube", lambda v, s: {"views": 1234, "avg_pct_viewed": 81, "subs_gained": 3})
    conn = analytics.connect(tmp_path / "a.db")
    assert stats_fetch.fetch(log=lambda *_: None, conn=conn) == 1
    assert stats_fetch.fetch(log=lambda *_: None, conn=conn) == 0            # same bucket isn't fetched twice
    assert conn.execute("SELECT views, hours_after, hook FROM video_metrics").fetchone() == (1234, 24, "T1")


def test_dashboard_builds_with_week_grid_videos_and_health(tmp_path, monkeypatch):
    from engine import dashboard
    monkeypatch.setattr(dashboard, "OUT", tmp_path / "dashboard.html")
    html = dashboard.build().read_text(encoding="utf-8")
    for part in ("Next 7 days", "System health", "Needs you", "class=gallery", "class=kpis6", "Waiting for your tap"):
        assert part in html, part
    assert "max-width:1240px" not in html                      # full width


def test_live_counters_add_videos_without_snapshots(tmp_path, monkeypatch):
    """17 Nov: Analytics lags 2-3 days; the live public counters fill the gap."""
    import json
    from engine import stats_fetch
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    live = tmp_path / "live.json"
    live.write_text(json.dumps({"videos": {"abc": {"channel": "brain_snack", "item": "i1", "views": 1001, "likes": 5,
                                                    "posted_at": time.time() - 86400, "title": "t"}},
                                "channels": {"brain_snack": {"subs": 1}}, "history": {}}))
    monkeypatch.setattr(stats_fetch, "LIVE", live)
    m = dashboard._metrics()["brain_snack"]
    assert m["videos"] == 1 and m["views"] == 1001
    assert dashboard._followers()["brain_snack"]["youtube"] == 1
