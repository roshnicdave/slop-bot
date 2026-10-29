from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cyberquiz.store import connect
from cyberquiz.trends import daily, suggest


class TrendDiscoveryTests(unittest.TestCase):
    def test_topic_wide_reels_are_selected_and_cached_without_media_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            seen = []

            def graph(method, path, params, **kwargs):
                seen.append(path)
                if path == "ig_hashtag_search":
                    return {"data": [{"id": "topic"}]}
                return {
                    "data": [
                        {
                            "id": "r1",
                            "media_type": "VIDEO",
                            "permalink": "https://www.instagram.com/reel/example/",
                            "caption": "How DNS fails",
                            "like_count": 300,
                            "comments_count": 20,
                            "media_url": "https://example.com/temporary-private-cdn-url",
                        },
                        {
                            "id": "image",
                            "media_type": "IMAGE",
                            "permalink": "https://www.instagram.com/p/image/",
                        },
                    ]
                }

            with (
                patch(
                    "cyberquiz.trends.config",
                    return_value={"discovery_hashtags": ["cybersecurity"]},
                ),
                patch(
                    "cyberquiz.providers.secrets",
                    return_value={
                        "IG_ACCESS_TOKEN": "private",
                        "IG_USER_ID": "private",
                    },
                ),
                patch("cyberquiz.instagram.graph", side_effect=graph),
                patch(
                    "cyberquiz.cloudflare.llm",
                    return_value={
                        "selected_ids": ["r1"],
                        "next_topics": ["dnssecurity"],
                    },
                ),
            ):
                result = daily(db)
                daily(db)
            self.assertEqual(seen.count("ig_hashtag_search"), 1)
            self.assertEqual(result["reels_discovered"], 1)
            self.assertEqual(
                result["examples"][0]["evidence"], "caption_and_public_counts_only"
            )
            self.assertNotIn(
                "temporary-private-cdn-url",
                " ".join(
                    str(tuple(r)) for r in db.execute("SELECT * FROM trend_posts")
                ),
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM trend_topics").fetchone()[0], 2
            )
            db.close()

    def test_search_suggestions_are_data_not_arbitrary_urls_or_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            suggest(
                db, ["#DNSsecurity", "https://evil.test", "x; shutdown", {"bad": True}]
            )
            self.assertEqual(
                [r[0] for r in db.execute("SELECT tag FROM trend_topics")],
                ["dnssecurity"],
            )
            db.close()

    def test_inspection_uses_temporary_files_and_labels_excerpt_scope(self):
        from cyberquiz.trend_inspection import inspect
        import subprocess
        from types import SimpleNamespace
        from PIL import Image
        from contextlib import contextmanager
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            @contextmanager
            def scratch(**kwargs):
                path = root / "scratch"
                path.mkdir()
                try:
                    yield str(path)
                finally:
                    import shutil

                    shutil.rmtree(path)

            def run(args, **kwargs):
                if "-hide_banner" in args:
                    return SimpleNamespace(
                        stderr="Duration: 00:00:12.00\nStream: Video: h264, 1080x1920\nStream: Audio: aac"
                    )
                target = Path(args[-1])
                if target.suffix == ".jpg":
                    Image.new("RGB", (240, 426)).save(target)
                else:
                    target.write_bytes(b"audio")
                return subprocess.CompletedProcess(args, 0)

            response = Mock(status_code=200)
            response.iter_content.return_value = [b"video"]
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            results = [
                Mock(json=lambda: {"result": {"text": "Why does DNS fail?"}}),
                Mock(
                    json=lambda: {
                        "result": {
                            "response": '{"niche_relevant":true,"format":"explainer"}'
                        }
                    }
                ),
            ]
            with (
                patch(
                    "cyberquiz.trend_inspection.tempfile.TemporaryDirectory",
                    side_effect=scratch,
                ),
                patch("cyberquiz.trend_inspection.requests.get", return_value=response),
                patch("cyberquiz.trend_inspection.subprocess.run", side_effect=run),
                patch(
                    "cyberquiz.trend_inspection.cloudflare.request", side_effect=results
                ),
            ):
                result = inspect(
                    None, "test", "https://video.cdninstagram.com/public.mp4"
                )
            self.assertEqual(result["findings"]["format"], "explainer")
            self.assertEqual(result["audio_seconds"], 12)
            self.assertFalse((root / "scratch").exists())

    def test_rolling_unique_hashtag_cap_blocks_new_topics(self):
        import datetime as dt
        from cyberquiz.trends import tables

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            tables(db)
            yesterday = (
                (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1))
                .date()
                .isoformat()
            )
            db.executemany(
                "INSERT INTO trend_queries VALUES(?,?,?)",
                [(f"old{i}", yesterday, "complete") for i in range(24)],
            )
            db.commit()
            with (
                patch(
                    "cyberquiz.trends.config",
                    return_value={"discovery_hashtags": ["newtopic"]},
                ),
                patch(
                    "cyberquiz.providers.secrets",
                    return_value={
                        "IG_ACCESS_TOKEN": "private",
                        "IG_USER_ID": "private",
                    },
                ),
                patch("cyberquiz.instagram.graph") as graph,
            ):
                result = daily(db)
                graph.assert_not_called()
            self.assertEqual(result["topics"], [])
            db.close()

    def test_top_feed_failure_does_not_prevent_recent_reel_discovery(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")

            def graph(method, path, **kwargs):
                if path == "ig_hashtag_search":
                    return {"data": [{"id": "topic"}]}
                if path.endswith("/top_media"):
                    raise RuntimeError("Feed unavailable")
                return {
                    "data": [
                        {
                            "id": "fresh",
                            "media_type": "VIDEO",
                            "permalink": "https://www.instagram.com/reel/fresh/",
                            "caption": "A DNS puzzle",
                        }
                    ]
                }

            with (
                patch(
                    "cyberquiz.trends.config",
                    return_value={"discovery_hashtags": ["cybersecurity"]},
                ),
                patch(
                    "cyberquiz.providers.secrets",
                    return_value={
                        "IG_ACCESS_TOKEN": "private",
                        "IG_USER_ID": "private",
                    },
                ),
                patch("cyberquiz.instagram.graph", side_effect=graph),
                patch(
                    "cyberquiz.cloudflare.llm", return_value={"selected_ids": ["fresh"]}
                ),
            ):
                result = daily(db)
            self.assertEqual(result["reels_discovered"], 1)
            self.assertEqual(result["limitations"][0]["feed"], "top_media")
            db.close()

    def test_completed_vision_result_is_reused_when_structuring_prose(self):
        import json
        from unittest.mock import Mock
        from cyberquiz.trend_inspection import model_result, normalize
        from cyberquiz.cloudflare import VISION, EDITOR

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            db.execute(
                "CREATE TABLE cf_calls(operation TEXT PRIMARY KEY,status TEXT,result TEXT)"
            )
            db.execute(
                "INSERT INTO cf_calls VALUES(?,?,?)",
                (
                    "clip:vision",
                    "complete",
                    json.dumps(
                        {
                            "success": True,
                            "result": {
                                "response": "First frame asks how DNS works. Later frames show a diagram."
                            },
                        }
                    ),
                ),
            )
            db.commit()
            response = Mock(
                json=lambda: {
                    "success": True,
                    "result": {
                        "response": '{"niche_relevant":true,"format":"explainer"}'
                    },
                }
            )
            with patch(
                "cyberquiz.trend_inspection.cloudflare.request", return_value=response
            ) as request:
                cached = model_result(db, "clip:vision", VISION, {}, 140)
                findings = normalize(db, "clip", cached["result"]["response"])
                self.assertEqual(findings["format"], "explainer")
                request.assert_called_once()
                self.assertEqual(request.call_args.args[1], "clip:normalize")
                self.assertEqual(request.call_args.args[3], EDITOR)
            db.close()

    def test_creator_frontier_comes_from_public_mentions_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            queried = []

            def graph(method, path, params, **kwargs):
                if path == "ig_hashtag_search":
                    return {"data": [{"id": "topic"}]}
                if path == "own_account":
                    queried.append(params["fields"])
                    return {"business_discovery": {"media": {"data": []}}}
                return {
                    "data": [
                        {
                            "id": "r1",
                            "media_type": "VIDEO",
                            "permalink": "https://www.instagram.com/reel/example/",
                            "caption": "Networking lesson by @alpha @beta @gamma",
                        }
                    ]
                }

            with (
                patch(
                    "cyberquiz.trends.config",
                    return_value={"discovery_hashtags": ["ccna"]},
                ),
                patch(
                    "cyberquiz.providers.secrets",
                    return_value={
                        "IG_ACCESS_TOKEN": "private",
                        "IG_USER_ID": "own_account",
                    },
                ),
                patch("cyberquiz.instagram.graph", side_effect=graph),
                patch(
                    "cyberquiz.cloudflare.llm", return_value={"selected_ids": ["r1"]}
                ),
            ):
                result = daily(db)
            self.assertEqual(result["creator_frontier_size"], 3)
            self.assertEqual(len(queried), 2)
            self.assertTrue(all("business_discovery.username(" in q for q in queried))
            db.close()
