import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cyberquiz.store import connect, new_job, now
from cyberquiz.experiments import tables, ensure, assign, evaluate


class ExperimentTests(unittest.TestCase):
    def test_low_reach_experiment_expires_without_adopting_a_winner(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            self.addCleanup(db.close)
            tables(db)
            db.execute(
                "INSERT INTO experiments VALUES(?,?,?,?,?,?,?,NULL)",
                (
                    "exp",
                    "testing",
                    "decision_seconds",
                    "5",
                    "3",
                    "test",
                    "2020-01-01T00:00:00+00:00",
                ),
            )
            db.commit()
            with (
                patch(
                    "cyberquiz.experiments.config",
                    return_value={"experiment_max_days": 14},
                ),
                patch("cyberquiz.telegram.update_config") as update,
            ):
                self.assertIsNone(evaluate(db))
                update.assert_not_called()
            row = db.execute("SELECT state,outcome FROM experiments").fetchone()
            self.assertEqual(row["state"], "inconclusive")
            self.assertEqual(
                json.loads(row["outcome"])["counts"], {"baseline": 0, "challenger": 0}
            )

    def test_model_proposes_new_value_and_unsafe_parameters_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            with (
                patch(
                    "cyberquiz.experiments.config", return_value={"decision_seconds": 5}
                ),
                patch(
                    "cyberquiz.experiments.cloudflare.llm",
                    return_value={
                        "parameter": "monthly_budget_usd",
                        "challenger": 100,
                        "hypothesis": "spend more",
                    },
                ),
            ):
                self.assertIsNone(ensure(db, {}))
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM experiments").fetchone()[0], 0
                )
            db.execute("DELETE FROM experiment_decisions")
            db.commit()
            with (
                patch(
                    "cyberquiz.experiments.config", return_value={"decision_seconds": 5}
                ),
                patch(
                    "cyberquiz.experiments.cloudflare.llm",
                    return_value={
                        "parameter": "decision_seconds",
                        "challenger": 3,
                        "hypothesis": "less waiting may reduce exits",
                    },
                ),
            ):
                exp = ensure(db, {})
                self.assertEqual(json.loads(exp["challenger"]), 3)
                p = {"diagram": {"kind": "flow"}}
                first = assign(db, p, "job")
                self.assertEqual(first["experiment"]["arm"], "baseline")
                j = new_job(db, "test")
                db.execute("UPDATE jobs SET plan=? WHERE id=?", (json.dumps(first), j))
                db.commit()
                self.assertEqual(
                    assign(db, p, "next")["experiment"]["arm"], "challenger"
                )
            db.close()

    def test_adoption_requires_comparable_samples_and_positive_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            tables(db)
            db.execute(
                "INSERT INTO experiments VALUES(?,?,?,?,?,?,?,NULL)",
                ("exp", "testing", "decision_seconds", "5", "3", "test", now()),
            )
            db.commit()
            with patch("cyberquiz.telegram.update_config") as update:
                evaluate(db)
                update.assert_not_called()
                for arm, shares in [("baseline", 10), ("challenger", 1)]:
                    for n in range(10):
                        j = new_job(db, "test")
                        media = arm + str(n)
                        p = {"experiment": {"id": "exp", "arm": arm}}
                        db.execute(
                            'UPDATE jobs SET status="published",media_id=?,plan=? WHERE id=?',
                            (media, json.dumps(p), j),
                        )
                        payload = {
                            k: {"data": [{"values": [{"value": v}]}]}
                            for k, v in [("reach", 1000), ("shares", shares)]
                        }
                        db.execute(
                            "INSERT INTO metrics VALUES(?,?,?,?)",
                            (media, now(), 72, json.dumps(payload)),
                        )
                db.commit()
                evaluate(db)
                update.assert_not_called()
                for media, payload in db.execute(
                    "SELECT media_id,payload FROM metrics"
                ).fetchall():
                    data = json.loads(payload)
                    follows = 10 if media.startswith("challenger") else 0
                    data["follows"] = {"data": [{"values": [{"value": follows}]}]}
                    db.execute(
                        "UPDATE metrics SET payload=? WHERE media_id=?",
                        (json.dumps(data), media),
                    )
                db.commit()
                evaluate(db)
                update.assert_called_once_with({"decision_seconds": 3})
                self.assertEqual(
                    db.execute("SELECT state FROM experiments").fetchone()[0], "adopted"
                )
            db.close()
