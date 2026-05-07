#
# Tests for OCI IoT raw-command publishing.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

from file_agent.iot_raw import send_payload, send_response
from file_agent.models import ProtocolResponse


class _FakeIOTClient:
    def __init__(self):
        self.calls = []

    def invoke_raw_command(
        self, *, digital_twin_instance_id, invoke_raw_command_details
    ):
        self.calls.append((digital_twin_instance_id, invoke_raw_command_details))
        return type("Response", (), {"status": 202, "data": None})()


def test_send_response_invokes_raw_json_command_with_protocol_payload():
    client = _FakeIOTClient()
    response = ProtocolResponse(
        op="prepare-upload",
        id="txn-1",
        data={
            "upload_url": (
                "https://objectstorage.example/p/token/"
                "ocid1.iotdigitaltwininstance.oc1..device/txn-1/"
            )
        },
        code=200,
        message="Upload prepared",
    )

    send_response(
        iot_client=client,
        digital_twin_instance_id="ocid1.iotdigitaltwininstance.oc1..device",
        endpoint="iot/v1/file/rsp",
        response=response,
    )

    [(digital_twin_instance_id, details)] = client.calls
    assert digital_twin_instance_id == "ocid1.iotdigitaltwininstance.oc1..device"
    assert details.request_endpoint == "iot/v1/file/rsp"
    assert details.request_duration == "PT60M"
    assert details.request_data == response.to_payload()


def test_send_payload_allows_bad_request_without_protocol_envelope():
    client = _FakeIOTClient()

    send_payload(
        iot_client=client,
        digital_twin_instance_id="ocid1.iotdigitaltwininstance.oc1..device",
        endpoint="iot/v1/file/rsp",
        payload={"code": 400, "message": "Bad request"},
    )

    [(digital_twin_instance_id, details)] = client.calls
    assert digital_twin_instance_id == "ocid1.iotdigitaltwininstance.oc1..device"
    assert details.request_data == {"code": 400, "message": "Bad request"}
