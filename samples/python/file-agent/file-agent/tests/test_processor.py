#
# Tests for file-agent protocol processing.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

import logging
import sys
from types import SimpleNamespace

from file_agent.models import InboundMessage
from file_agent.processor import MessageProcessor


class _FakePARService:
    def __init__(self):
        self.stage_result = SimpleNamespace(
            par_id="par-id",
            upload_url=(
                "https://objectstorage.example/p/token/"
                "ocid1.iotdigitaltwininstance.oc1..device/txn-1/"
            ),
            object_prefix="ocid1.iotdigitaltwininstance.oc1..device/txn-1/",
        )
        self.stage_exception = None
        self.complete_result = True
        self.stage_calls = []
        self.complete_calls = []

    def stage_upload(
        self, digital_twin_instance_id, transaction_id, requested_ttl_minutes
    ):
        self.stage_calls.append(
            (digital_twin_instance_id, transaction_id, requested_ttl_minutes)
        )
        if self.stage_exception:
            raise self.stage_exception
        return self.stage_result

    def complete_upload(self, digital_twin_instance_id, transaction_id):
        self.complete_calls.append((digital_twin_instance_id, transaction_id))
        return self.complete_result


def _message(value):
    return InboundMessage.model_validate(
        {
            "digitalTwinInstanceId": "ocid1.iotdigitaltwininstance.oc1..device",
            "timeObserved": "2026-04-28T12:00:00Z",
            "contentPath": "file.commandDetails",
            "value": value,
        }
    )


def _processor(par_service=None, commands=None, runner=None):
    responses = []
    processor = MessageProcessor(
        par_service=par_service or _FakePARService(),
        commands=commands or {},
        responder=lambda message, response: responses.append(response.to_payload()),
        command_runner=runner,
    )
    return processor, responses


def test_prepare_upload_creates_par_and_returns_upload_url():
    par_service = _FakePARService()
    processor, responses = _processor(par_service=par_service)

    processor.handle_message(
        _message({"op": "prepare-upload", "id": "txn-1", "data": {"ttl": 120}})
    )

    assert par_service.stage_calls == [
        ("ocid1.iotdigitaltwininstance.oc1..device", "txn-1", 120)
    ]
    assert responses == [
        {
            "op": "prepare-upload",
            "id": "txn-1",
            "data": {
                "upload_url": (
                    "https://objectstorage.example/p/token/"
                    "ocid1.iotdigitaltwininstance.oc1..device/txn-1/"
                )
            },
            "code": 200,
            "message": "Upload prepared",
        }
    ]


def test_prepare_upload_service_error_sends_500():
    par_service = _FakePARService()
    par_service.stage_exception = RuntimeError("boom")
    processor, responses = _processor(par_service=par_service)

    processor.handle_message(
        _message({"op": "prepare-upload", "id": "txn-1", "data": {"ttl": 60}})
    )

    assert responses[-1]["code"] == 500
    assert responses[-1]["message"] == "Upload preparation failed"


def test_complete_upload_deletes_par_and_completes_when_no_command_requested():
    par_service = _FakePARService()
    processor, responses = _processor(par_service=par_service)

    processor.handle_message(
        _message({"op": "complete-upload", "id": "txn-1", "data": {}})
    )

    assert par_service.complete_calls == [
        ("ocid1.iotdigitaltwininstance.oc1..device", "txn-1")
    ]
    assert responses == [
        {
            "op": "complete-upload",
            "id": "txn-1",
            "data": {},
            "code": 200,
            "message": "Process completed",
        }
    ]


def test_complete_upload_rejects_missing_prepared_upload():
    par_service = _FakePARService()
    par_service.complete_result = False
    processor, responses = _processor(par_service=par_service)

    processor.handle_message(
        _message({"op": "complete-upload", "id": "txn-1", "data": {}})
    )

    assert responses[-1]["code"] == 422
    assert responses[-1]["message"] == "No prepared upload"


def test_complete_upload_rejects_unknown_command_after_par_cleanup():
    par_service = _FakePARService()
    processor, responses = _processor(par_service=par_service, commands={})

    processor.handle_message(
        _message(
            {
                "op": "complete-upload",
                "id": "txn-1",
                "data": {"command": "missing", "parameters": {}},
            }
        )
    )

    assert par_service.complete_calls == [
        ("ocid1.iotdigitaltwininstance.oc1..device", "txn-1")
    ]
    assert responses[-1]["code"] == 422
    assert responses[-1]["message"] == "Invalid command"


def test_complete_upload_with_command_sends_queued_started_completed():
    runner_calls = []

    def runner(args):
        runner_calls.append(args)
        return SimpleNamespace(returncode=0)

    processor, responses = _processor(
        commands={"demo": "/opt/demo.sh"},
        runner=runner,
    )

    processor.handle_message(
        _message(
            {
                "op": "complete-upload",
                "id": "txn-1",
                "data": {"command": "demo", "parameters": {"artifacts": ["x"]}},
            }
        )
    )

    assert [response["code"] for response in responses] == [202, 201, 200]
    assert [response["message"] for response in responses] == [
        "Process queued",
        "Process started",
        "Process completed",
    ]
    assert runner_calls[0][0] == "/opt/demo.sh"
    assert '"op":"complete-upload"' in runner_calls[0][1]


def test_default_command_runner_logs_stdout_and_stderr_lines(caplog):
    caplog.set_level(logging.INFO, logger="file_agent.processor")

    result = MessageProcessor._default_command_runner(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "print('stdout line 1')\n"
                "print('stdout line 2')\n"
                "print('stderr line 1', file=sys.stderr)\n"
                "print('stderr line 2', file=sys.stderr)\n"
            ),
        ]
    )

    stdout_records = [
        record
        for record in caplog.records
        if record.name == "file_agent.processor" and record.levelno == logging.INFO
    ]
    stderr_records = [
        record
        for record in caplog.records
        if record.name == "file_agent.processor" and record.levelno == logging.ERROR
    ]

    assert result.returncode == 0
    assert [record.message for record in stdout_records] == [
        "stdout line 1",
        "stdout line 2",
    ]
    assert [record.threadName for record in stdout_records] == ["stdout", "stdout"]
    assert [record.message for record in stderr_records] == [
        "stderr line 1",
        "stderr line 2",
    ]
    assert [record.threadName for record in stderr_records] == ["stderr", "stderr"]
