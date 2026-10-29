"""Obtain short-lived Lightsail SSH credentials without printing them."""

import json
import os
from pathlib import Path
import subprocess


def access():
    settings_path = Path(__file__).with_name("aws.local.json")
    if not settings_path.exists():
        raise RuntimeError(
            "Copy deploy/aws.example.json to deploy/aws.local.json and set the target instance"
        )
    settings = json.loads(settings_path.read_text())
    result = subprocess.run(
        [
            "aws",
            "lightsail",
            "get-instance-access-details",
            "--region",
            settings["region"],
            "--instance-name",
            settings["instance_name"],
            "--protocol",
            "ssh",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    a = json.loads(result.stdout)["accessDetails"]
    folder = Path.home() / ".config/cyber-quiz"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = folder / "aws-temporary-key"
    for path, value in [
        (key, a["privateKey"]),
        (Path(str(key) + "-cert.pub"), a["certKey"]),
    ]:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(value)
    host = {"ip": a["ipAddress"], "username": a["username"], "key_path": str(key)}
    (folder / "aws-host.json").write_text(json.dumps(host))
    return host


if __name__ == "__main__":
    import sys

    h = access()
    command = sys.argv[1:]
    if not command:
        print("Short-lived SSH access ready.")
        raise SystemExit()
    raise SystemExit(
        subprocess.run(
            [
                "ssh",
                "-i",
                h["key_path"],
                "-o",
                "BatchMode=yes",
                h["username"] + "@" + h["ip"],
                *command,
            ]
        ).returncode
    )
