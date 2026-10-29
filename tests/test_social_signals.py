import datetime as dt
import tempfile
from pathlib import Path
import unittest
from cyberquiz.store import connect
from cyberquiz.social_signals import observe, analyze


class SocialSignalsTests(unittest.TestCase):
    def test_daily_observations_are_idempotent_and_measure_growth(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            clock = dt.datetime.now(dt.timezone.utc)
            def sample(offset, likes):
                observed = clock - dt.timedelta(hours=offset)
                return {"checked_at": observed.isoformat(), "competitors": [{
                    "username": "example", "observed_at": observed.isoformat(),
                    "data": {"followers_count": 1000, "media": {"data": [{
                        "id": "p1", "timestamp": (clock-dt.timedelta(hours=48)).isoformat(),
                        "media_type": "VIDEO", "like_count": likes, "comments_count": 10,
                        "caption": "A useful diagram", "permalink": "https://example.com/reel/1"
                    }]}}}]}
            observe(db, sample(24, 100))
            latest = sample(0, 340)
            observe(db, latest)
            observe(db, latest)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM social_observations").fetchone()[0], 2)
            result = analyze(db)["candidate_videos"][0]
            self.assertEqual(result["observed_growth_per_hour"], 10)
            self.assertIsNone(result["relative_to_account_age_matched_median"])
            self.assertNotIn("viral", result)
            db.close()

    def test_empty_or_missing_counts_do_not_invent_success(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            observe(db, {"competitors": []})
            self.assertEqual(analyze(db)["candidate_videos"], [])
            db.close()
