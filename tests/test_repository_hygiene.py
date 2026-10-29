"""Check tracked source, not ignored local deployment state."""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    @unittest.skipUnless(
        (ROOT / ".git").exists(), "Git metadata is absent in deployment archives"
    )
    def test_no_runtime_files_credentials_or_personal_mac_paths(self):
        names = (
            subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
            .decode()
            .split("\0")
        )
        forbidden = {
            "config.json",
            "config.defaults.json",
            "credentials.json",
            ".env",
            "cloudflare/wrangler.jsonc",
            "deploy/aws.local.json",
            "deploy/Caddyfile",
        }
        patterns = [
            r"/Users/[A-Za-z0-9_.-]+/",
            r"EA[A-Za-z0-9]{90,}",
            r"\bsk-[A-Za-z0-9]{28,}",
            r"\b\d{8,12}:AA[A-Za-z0-9_-]{25,}",
            r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY",
        ]
        findings = []
        for name in filter(None, names):
            if name in forbidden or (
                name.startswith(("data/", "out/")) and not name.endswith("/.gitkeep")
            ):
                findings.append(name)
                continue
            path = ROOT / name
            if not path.is_file():
                continue
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            if any(re.search(pattern, text) for pattern in patterns):
                findings.append(name)
        self.assertEqual(
            findings,
            [],
            "Remove private/runtime material from tracked files; do not print its contents.",
        )
