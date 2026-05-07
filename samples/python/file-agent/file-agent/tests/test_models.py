#
# Tests for file-agent protocol models.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

import pytest
from pydantic import ValidationError

from file_agent.models import (
    InboundMessage,
    PARRequestData,
    ProtocolRequest,
    ProtocolResponse,
    UploadRequestData,
)


def _message_payload(value):
    return {
        "digitalTwinInstanceId": "ocid1.iotdigitaltwininstance.oc1..device",
        "timeObserved": "2026-04-28T12:00:00Z",
        "contentPath": "file.commandDetails",
        "value": value,
    }


def test_prepare_upload_request_exposes_ttl_data():
    message = InboundMessage.model_validate(
        _message_payload(
            {
                "op": "prepare-upload",
                "id": "txn-1",
                "data": {"ttl": 120},
            }
        )
    )

    assert message.request.op == "prepare-upload"
    assert message.request.id == "txn-1"
    assert PARRequestData.model_validate(message.request.data).ttl == 120


def test_inbound_message_normalizes_camel_case_input_to_snake_case_fields():
    message = InboundMessage.model_validate(
        _message_payload({"op": "prepare-upload", "id": "txn-1", "data": {}})
    )

    assert message.digital_twin_instance_id == (
        "ocid1.iotdigitaltwininstance.oc1..device"
    )
    assert message.time_observed == "2026-04-28T12:00:00Z"
    assert message.content_path == "file.commandDetails"
    assert message.request.id == "txn-1"

    serialized = message.model_dump(by_alias=True)

    assert serialized["digital_twin_instance_id"] == (
        "ocid1.iotdigitaltwininstance.oc1..device"
    )
    assert serialized["time_observed"] == "2026-04-28T12:00:00Z"
    assert serialized["content_path"] == "file.commandDetails"
    assert serialized["request"]["id"] == "txn-1"
    assert "digitalTwinInstanceId" not in serialized
    assert "timeObserved" not in serialized
    assert "contentPath" not in serialized
    assert "value" not in serialized


def test_inbound_message_rejects_snake_case_field_names_for_aliased_fields():
    payload = {
        "digital_twin_instance_id": "ocid1.iotdigitaltwininstance.oc1..device",
        "time_observed": "2026-04-28T12:00:00Z",
        "content_path": "file.commandDetails",
        "request": {"op": "prepare-upload", "id": "txn-1", "data": {"ttl": 120}},
    }

    with pytest.raises(ValidationError):
        InboundMessage.model_validate(payload)


def test_complete_upload_request_allows_optional_command():
    request = ProtocolRequest.model_validate(
        {
            "op": "complete-upload",
            "id": "txn-1",
            "data": {
                "command": "demo",
                "parameters": {"artifacts": ["reads.fastq"]},
            },
        }
    )

    upload_data = UploadRequestData.model_validate(request.data)

    assert upload_data.command == "demo"
    assert upload_data.parameters == {"artifacts": ["reads.fastq"]}


def test_unknown_operation_is_rejected():
    with pytest.raises(ValidationError):
        ProtocolRequest.model_validate({"op": "bad-op", "id": "txn-1", "data": {}})


@pytest.mark.parametrize(
    "transaction_id",
    [
        "txn/1",
        "txn?1",
        "txn#1",
        "txn%2f1",
        ".",
        "..",
        "txn 1",
        "txn\n1",
        "x" * 129,
    ],
)
def test_transaction_id_rejects_unsafe_path_and_url_components(transaction_id):
    with pytest.raises(ValidationError):
        ProtocolRequest.model_validate(
            {"op": "prepare-upload", "id": transaction_id, "data": {}}
        )


def test_protocol_response_payload_matches_readme_shape():
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

    assert response.to_payload() == {
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
