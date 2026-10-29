"""Run from Mac. Uploads only this pipeline and its isolated credentials."""

import pathlib
import sqlite3
import subprocess
import tarfile
import tempfile
import sys

root = pathlib.Path(__file__).resolve().parents[1]
from aws_access import access

h = access()
ssh = ["ssh", "-i", h["key_path"], "-o", "BatchMode=yes", h["username"] + "@" + h["ip"]]
scp = ["scp", "-q", "-i", h["key_path"]]
with tempfile.TemporaryDirectory() as temp:
    temp = pathlib.Path(temp)
    with (
        sqlite3.connect(root / "data/state.sqlite") as src,
        sqlite3.connect(temp / "state.sqlite") as dest,
    ):
        src.backup(dest)
    with tarfile.open(temp / "pipeline.tar.gz", "w:gz") as tar:
        for folder in ["cyberquiz", "tests", "deploy", "cloudflare", "assets"]:
            for path in (root / folder).rglob("*"):
                if (
                    path.is_file()
                    and "__pycache__" not in str(path)
                    and path.name not in ("aws.local.json", "wrangler.jsonc")
                ):
                    tar.add(path, arcname=str(path.relative_to(root)))
        for name in [
            "config.json",
            "requirements.txt",
            "README.md",
            "PROJECT_REQUIREMENTS.md",
            "AGENT_ARCHITECTURE.md",
            "OPERATIONS.md",
        ]:
            if (root / name).exists():
                tar.add(
                    root / name,
                    arcname="config.defaults.json" if name == "config.json" else name,
                )
        if (root / "research" / "quiz-observations.json").exists():
            tar.add(
                root / "research" / "quiz-observations.json",
                arcname="research/quiz-observations.json",
            )
        tar.add(temp / "state.sqlite", arcname="data/state.sqlite.bootstrap")
        for name in ["pricing-evidence.json", "kev-snapshot.json"]:
            if (root / "data" / name).exists():
                tar.add(root / "data" / name, arcname="data/" + name)
    subprocess.run(
        scp
        + [
            str(temp / "pipeline.tar.gz"),
            h["username"] + "@" + h["ip"] + ":/tmp/cyberquiz-pipeline.tar.gz",
        ],
        check=True,
    )
    subprocess.run(
        ssh
        + [
            "set -e; mkdir -p ~/cyber-quiz; tar -xzf /tmp/cyberquiz-pipeline.tar.gz -C ~/cyber-quiz; python3 ~/cyber-quiz/deploy/merge_config.py; if [ ! -f ~/cyber-quiz/data/state.sqlite ]; then mv ~/cyber-quiz/data/state.sqlite.bootstrap ~/cyber-quiz/data/state.sqlite; fi; chmod 700 ~/.config/cyber-quiz"
        ],
        check=True,
    )
    exists = subprocess.run(
        ssh + ["test -f ~/.config/cyber-quiz/credentials.json"]
    ).returncode
    if exists not in (0, 1):
        raise RuntimeError("Could not check remote credential file")
    if exists == 1 or "--sync-secrets" in sys.argv:
        subprocess.run(
            scp
            + [
                str(pathlib.Path.home() / ".config/cyber-quiz/credentials.json"),
                h["username"] + "@" + h["ip"] + ":.config/cyber-quiz/credentials.json",
            ],
            check=True,
        )
    subprocess.run(
        ssh
        + [
            'set -e; chmod 600 ~/.config/cyber-quiz/credentials.json; cd ~/cyber-quiz; PATH="$HOME/cyber-quiz/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -v; PATH="$HOME/cyber-quiz/.venv/bin:$PATH" .venv/bin/python -m cyberquiz doctor'
        ],
        check=True,
    )
print("Deployment checked. Production ledger preserved; no paid inference calls.")
