#
# Tests for the demo command script.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_COMMAND = REPO_ROOT / "commands" / "demo.sh"


def _sample_message(**parameters):
    return {
        "message_id": "0102",
        "digital_twin_instance_id": "ocid1.iotdigitaltwininstance.oc1..device",
        "digital_twin_display_name": "demo-device",
        "time_observed": "2026-04-29T19:00:00Z",
        "content_path": "file.commandDetails",
        "request": {
            "op": "complete-upload",
            "id": "txn-1",
            "data": {
                "command": "demo",
                "parameters": {"artifacts": ["reads.fastq"], **parameters},
            },
        },
    }


def _run_demo(message, **kwargs):
    return subprocess.run(
        [str(DEMO_COMMAND), message],
        capture_output=True,
        check=False,
        text=True,
        **kwargs,
    )


def test_demo_command_displays_message_payload():
    result = _run_demo(json.dumps(_sample_message(sleep=0)))

    assert result.returncode == 0
    assert "demo.sh: Message ID   : 0102" in result.stdout
    assert "demo.sh: Instance ID  : ocid1.iotdigitaltwininstance.oc1..device" in (
        result.stdout
    )
    assert "demo.sh: Request Id: txn-1" in result.stdout
    assert '"artifacts": [' in result.stdout
    assert "demo.sh: sleeping for 0 seconds" in result.stdout
    assert "demo.sh: Done" in result.stdout
    assert result.stderr == ""


def test_demo_command_rejects_invalid_json():
    result = _run_demo("not-json")

    assert result.returncode == 1
    assert "demo.sh: invalid message JSON" in result.stderr
    assert "demo.sh: Done" not in result.stdout


def test_demo_command_rejects_invalid_sleep_parameter():
    result = _run_demo(json.dumps(_sample_message(sleep="not-a-number")))

    assert result.returncode == 1
    assert "demo.sh: parameters.sleep must be a non-negative number" in result.stderr
    assert "demo.sh: Done" not in result.stdout


def test_demo_command_reports_missing_jq(tmp_path):
    bash = shutil.which("bash")
    assert bash is not None
    env = {**os.environ, "PATH": str(tmp_path)}

    result = subprocess.run(
        [bash, str(DEMO_COMMAND), json.dumps(_sample_message())],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert result.returncode == 127
    assert "demo.sh: jq is required" in result.stderr
