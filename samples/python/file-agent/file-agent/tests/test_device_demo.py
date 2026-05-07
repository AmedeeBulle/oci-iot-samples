#
# Tests for the file-agent device demo.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

from pathlib import Path

from file_agent import device_demo


class _FakeMQTTModule:
    MQTTv311 = "MQTTv311"

    class CallbackAPIVersion:
        VERSION2 = "VERSION2"

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.password = None
            self.tls_context = None
            self.username = None
            self.on_connect = None
            self.on_disconnect = None
            self.on_message = None
            self.on_subscribe = None

        def username_pw_set(self, username, password):
            self.username = username
            self.password = password

        def tls_set_context(self, context):
            self.tls_context = context


class _FakeHTTPResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def getcode(self):
        return self.status


def test_configure_mqtt_client_uses_tls_and_persistent_session():
    client = device_demo.configure_mqtt_client(
        client_id="device-demo",
        username="mqtt-user",
        password="mqtt-password",
        mqtt_module=_FakeMQTTModule,
    )

    assert client.kwargs["callback_api_version"] == "VERSION2"
    assert client.kwargs["client_id"] == "device-demo"
    assert client.kwargs["clean_session"] is False
    assert client.kwargs["protocol"] == "MQTTv311"
    assert client.username == "mqtt-user"
    assert client.password == "mqtt-password"
    assert client.tls_context is not None
    assert client.on_connect is None
    assert client.on_disconnect is None
    assert client.on_message is None
    assert client.on_subscribe is None


def test_parse_args_defaults_client_id_to_username():
    config = device_demo.parse_args(["mqtt.example.com", "mqtt-user", "secret"])

    assert config.client_id == "mqtt-user"


def test_prepare_upload_payload_contains_transaction_and_ttl():
    assert device_demo.prepare_upload_payload("txn-1", ttl_minutes=30) == {
        "op": "prepare-upload",
        "id": "txn-1",
        "data": {"ttl": 30},
    }


def test_mqtt_host_accepts_bare_host_or_endpoint_url():
    assert device_demo.mqtt_host("mqtt.example.com") == "mqtt.example.com"
    assert device_demo.mqtt_host("mqtt.example.com:8883") == "mqtt.example.com"
    assert device_demo.mqtt_host("mqtts://mqtt.example.com:8883") == (
        "mqtt.example.com"
    )


def test_complete_upload_payload_passes_uploaded_file_name_as_artifact():
    payload = device_demo.complete_upload_payload(
        transaction_id="txn-1",
        command="demo",
        file_name="reads fastq.txt",
    )

    assert payload == {
        "op": "complete-upload",
        "id": "txn-1",
        "data": {
            "command": "demo",
            "parameters": {
                "artifacts": ["reads fastq.txt"],
            },
        },
    }


def test_object_upload_url_appends_quoted_file_name():
    upload_url = "https://objectstorage.example/p/token/device/txn-1/"

    assert device_demo.object_upload_url(upload_url, "reads fastq.txt") == (
        "https://objectstorage.example/p/token/device/txn-1/reads%20fastq.txt"
    )


def test_upload_file_puts_file_bytes_to_object_url(tmp_path):
    file_path = tmp_path / "reads.fastq"
    file_path.write_bytes(b"demo reads\n")
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return _FakeHTTPResponse(200)

    object_url = device_demo.upload_file(
        upload_url="https://objectstorage.example/p/token/device/txn-1/",
        file_path=file_path,
        timeout_seconds=15,
        opener=opener,
    )

    [(request, timeout)] = calls
    assert (
        object_url == "https://objectstorage.example/p/token/device/txn-1/reads.fastq"
    )
    assert request.full_url == object_url
    assert request.get_method() == "PUT"
    assert request.data == b"demo reads\n"
    assert request.headers["Content-type"] == "application/octet-stream"
    assert timeout == 15


def test_default_test_file_is_created_with_demo_content(tmp_path):
    file_path = device_demo.create_default_test_file(tmp_path)

    assert file_path == Path(tmp_path) / "file-agent-device-demo.txt"
    assert "file-agent device demo upload" in file_path.read_text(encoding="utf-8")
