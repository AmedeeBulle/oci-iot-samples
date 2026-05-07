#
# Tests for Oracle DB/AQ IoT message handling.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

import queue
from types import SimpleNamespace

import pytest

from file_agent import iot_db


class _FakeCursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, parameters=None):
        self.executed.append((statement, parameters or {}))

    def fetchone(self):
        if self.rows:
            return self.rows.pop(0)
        return None

    def callfunc(self, name, return_type, args):
        return f"'{args[0]}'"

    def callproc(self, name, keyword_parameters=None):
        self.executed.append((name, keyword_parameters or {}))


class _FakeConnection:
    def __init__(self, rows=None, messages=None):
        self.cursor_instance = _FakeCursor(rows)
        self.messages = list(messages or [])
        self.commits = 0
        self.queue_instance = None

    def cursor(self):
        return self.cursor_instance

    def queue(self, name, payload_type):
        self.queue_instance = _FakeQueue(self.messages)
        return self.queue_instance

    def commit(self):
        self.commits += 1


class _FakeQueue:
    def __init__(self, messages):
        self.messages = messages
        self.deqOptions = SimpleNamespace()

    def deqone(self):
        if not self.messages:
            return None
        return self.messages.pop(0)


def _message(payload, msgid=b"\x01\x02"):
    return SimpleNamespace(payload=payload, msgid=msgid)


def _payload(value):
    return {
        "digitalTwinInstanceId": "ocid1.iotdigitaltwininstance.oc1..device",
        "timeObserved": "2026-04-28T12:00:00Z",
        "contentPath": "file.commandDetails",
        "value": value,
    }


def test_build_subscriber_rule_filters_by_display_name_and_content_path():
    connection = _FakeConnection(rows=[["ocid1.iotdigitaltwininstance.oc1..device"]])

    rule = iot_db.build_subscriber_rule(
        connection=connection,
        iot_domain_short_id="abc123",
        digital_twin_instance_id=None,
        display_name="device-1",
        content_path="file.commandDetails",
    )

    assert rule == (
        'tab.user_data."digitalTwinInstanceId" = '
        "'ocid1.iotdigitaltwininstance.oc1..device' and "
        "tab.user_data.\"contentPath\" = 'file.commandDetails'"
    )


def test_build_subscriber_rule_rejects_unknown_display_name():
    connection = _FakeConnection(rows=[])

    with pytest.raises(ValueError, match="No such display name"):
        iot_db.build_subscriber_rule(
            connection=connection,
            iot_domain_short_id="abc123",
            digital_twin_instance_id=None,
            display_name="missing",
            content_path="file.commandDetails",
        )


def test_dequeue_messages_reports_invalid_payload_to_callback():
    connection = _FakeConnection(
        messages=[_message({"digitalTwinInstanceId": "ocid1.device"})]
    )
    invalid = []

    iot_db.dequeue_messages(
        connection=connection,
        queue_name="ABC123__IOT.NORMALIZED_DATA",
        subscriber_name="file_agent",
        iot_domain_short_id="abc123",
        message_queue=queue.Queue(),
        invalid_message_handler=lambda instance_id, error: invalid.append(
            (instance_id, error)
        ),
        max_messages=1,
    )

    assert connection.commits == 1
    assert invalid[0][0] == "ocid1.device"


def test_dequeue_messages_forwards_valid_payload_with_display_name():
    payload = _payload({"op": "prepare-upload", "id": "txn-1", "data": {"ttl": 30}})
    connection = _FakeConnection(rows=[["device-1"]], messages=[_message(payload)])
    outbox = queue.Queue()

    iot_db.dequeue_messages(
        connection=connection,
        queue_name="ABC123__IOT.NORMALIZED_DATA",
        subscriber_name="file_agent",
        iot_domain_short_id="abc123",
        message_queue=outbox,
        max_messages=1,
    )

    message = outbox.get_nowait()
    assert message.message_id == "0102"
    assert message.digital_twin_display_name == "device-1"
    assert message.request.op == "prepare-upload"
    assert message.request.id == "txn-1"
    assert connection.queue_instance.deqOptions.consumername == "file_agent"
