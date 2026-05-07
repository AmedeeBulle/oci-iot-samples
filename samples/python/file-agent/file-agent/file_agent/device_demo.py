#
# MQTT device demo for file-agent.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

"""MQTT device demo for file-agent upload transactions."""

import argparse
import json
import logging
import queue
import ssl
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from urllib import request
from urllib.parse import quote, urlsplit, urlunsplit

MQTT_PORT = 8883
DEFAULT_COMMAND_TOPIC = "iot/v1/file/cmd"
DEFAULT_RESPONSE_TOPIC = "iot/v1/file/rsp"
DEFAULT_KEEPALIVE_SECONDS = 60

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceDemoConfig:
    """Runtime settings for the device demo."""

    endpoint: str
    username: str
    password: str
    client_id: str
    command_topic: str
    response_topic: str
    transaction_id: str
    ttl_minutes: int
    command: str
    file_path: Optional[Path]
    timeout_seconds: float


def prepare_upload_payload(transaction_id: str, ttl_minutes: int) -> dict[str, Any]:
    """Return the prepare-upload message payload."""
    return {
        "op": "prepare-upload",
        "id": transaction_id,
        "data": {"ttl": ttl_minutes},
    }


def complete_upload_payload(
    transaction_id: str,
    command: str,
    file_name: str,
) -> dict[str, Any]:
    """Return the complete-upload message payload for the uploaded file."""
    return {
        "op": "complete-upload",
        "id": transaction_id,
        "data": {
            "command": command,
            "parameters": {
                "artifacts": [file_name],
            },
        },
    }


def object_upload_url(upload_url: str, file_name: str) -> str:
    """Return the object URL for the file within the prepared upload directory."""
    parts = urlsplit(upload_url)
    path = parts.path
    if not path.endswith("/"):
        path = f"{path}/"
    path = f"{path}{quote(file_name)}"
    return urlunsplit(parts._replace(path=path))


def mqtt_host(endpoint: str) -> str:
    """Return the hostname from a bare host or MQTT endpoint URL."""
    parsed = urlsplit(endpoint if "://" in endpoint else f"//{endpoint}")
    return parsed.hostname or endpoint


def upload_file(
    upload_url: str,
    file_path: Path,
    timeout_seconds: float,
    opener: Callable[..., Any] = request.urlopen,
) -> str:
    """Upload a local file to the prepared Object Storage URL."""
    object_url = object_upload_url(upload_url, file_path.name)
    body = file_path.read_bytes()
    upload_request = request.Request(
        object_url,
        data=body,
        headers={"Content-Type": "application/octet-stream"},
        method="PUT",
    )
    logger.info("Uploading %s bytes to %s", len(body), object_url)
    with opener(upload_request, timeout=timeout_seconds) as response:
        status = response.getcode()
    if status < 200 or status >= 300:
        raise RuntimeError(f"Upload failed with HTTP status {status}")
    logger.info("Upload completed with HTTP status %s", status)
    return object_url


def create_default_test_file(directory: Path) -> Path:
    """Create and return a small test file for the demo upload."""
    file_path = directory / "file-agent-device-demo.txt"
    file_path.write_text(
        "file-agent device demo upload\n",
        encoding="utf-8",
    )
    return file_path


def configure_mqtt_client(
    client_id: str,
    username: str,
    password: str,
    mqtt_module=None,
):
    """Create a TLS MQTT client using a persistent MQTT session."""
    if mqtt_module is None:
        from paho.mqtt import client as mqtt_module

    client = mqtt_module.Client(
        callback_api_version=mqtt_module.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=False,
        protocol=mqtt_module.MQTTv311,
    )
    client.username_pw_set(username, password)
    client.tls_set_context(ssl.create_default_context())
    return client


def run_demo(config: DeviceDemoConfig) -> int:
    """Run the device-side upload demo."""
    connected = threading.Event()
    subscribed = threading.Event()
    responses: queue.Queue[dict[str, Any]] = queue.Queue()

    client = configure_mqtt_client(
        client_id=config.client_id,
        username=config.username,
        password=config.password,
    )

    def on_connect(client, userdata, flags, reason_code, properties):
        logger.info("Connected to MQTT endpoint: reason_code=%s", reason_code)
        connected.set()

    def on_disconnect(client, userdata, flags, reason_code, properties):
        logger.info("Disconnected from MQTT endpoint: reason_code=%s", reason_code)

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        logger.info("Subscribed to %s", config.response_topic)
        subscribed.set()

    def on_message(client, userdata, message):
        payload = message.payload.decode("utf-8")
        logger.info("Received on %s: %s", message.topic, payload)
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            logger.error("Ignoring non-JSON response payload")
            return
        responses.put(decoded)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    temporary_directory = None
    try:
        file_path = config.file_path
        if file_path is None:
            temporary_directory = tempfile.TemporaryDirectory()
            file_path = create_default_test_file(Path(temporary_directory.name))
        if not file_path.is_file():
            raise FileNotFoundError(f"Upload file not found: {file_path}")
        logger.info("Using upload file %s", file_path)

        host = mqtt_host(config.endpoint)
        logger.info("Connecting to %s:%s with TLS", host, MQTT_PORT)
        client.connect(
            host,
            MQTT_PORT,
            keepalive=DEFAULT_KEEPALIVE_SECONDS,
        )
        client.loop_start()
        if not connected.wait(config.timeout_seconds):
            raise TimeoutError("Timed out waiting for MQTT connection")

        logger.info("Subscribing to response topic %s", config.response_topic)
        client.subscribe(config.response_topic, qos=1)
        if not subscribed.wait(config.timeout_seconds):
            raise TimeoutError("Timed out waiting for response topic subscription")

        prepare_payload = prepare_upload_payload(
            config.transaction_id,
            config.ttl_minutes,
        )
        publish_json(client, config.command_topic, prepare_payload)
        prepare_response = wait_for_response(
            responses,
            transaction_id=config.transaction_id,
            operation="prepare-upload",
            timeout_seconds=config.timeout_seconds,
        )
        require_response_code(prepare_response, expected_code=200)

        upload_url = prepare_response.get("data", {}).get("upload_url")
        if not upload_url:
            raise RuntimeError("prepare-upload response did not include upload_url")

        upload_file(upload_url, file_path, config.timeout_seconds)

        complete_payload = complete_upload_payload(
            transaction_id=config.transaction_id,
            command=config.command,
            file_name=file_path.name,
        )
        publish_json(client, config.command_topic, complete_payload)
        complete_response = wait_for_terminal_response(
            responses,
            transaction_id=config.transaction_id,
            operation="complete-upload",
            timeout_seconds=config.timeout_seconds,
        )
        require_response_code(complete_response, expected_code=200)
    finally:
        logger.info("Disconnecting from MQTT endpoint")
        client.disconnect()
        client.loop_stop()
        if temporary_directory is not None:
            temporary_directory.cleanup()

    logger.info("Device demo completed")
    return 0


def publish_json(client, topic: str, payload: dict[str, Any]) -> None:
    """Publish a JSON MQTT message and wait for it to leave the client."""
    encoded = json.dumps(payload, separators=(",", ":"))
    logger.info("Publishing to %s: %s", topic, json.dumps(payload, indent=2))
    publish_info = client.publish(topic, encoded, qos=1)
    publish_info.wait_for_publish()


def wait_for_response(
    responses: queue.Queue[dict[str, Any]],
    transaction_id: str,
    operation: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Wait for the next response matching an operation and transaction."""
    end_time = time.monotonic() + timeout_seconds
    while True:
        remaining = end_time - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for {operation} response")
        response = responses.get(timeout=remaining)
        if response.get("id") == transaction_id and response.get("op") == operation:
            return response
        logger.info("Ignoring response for different transaction or operation")


def wait_for_terminal_response(
    responses: queue.Queue[dict[str, Any]],
    transaction_id: str,
    operation: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Wait for a terminal response code for an operation and transaction."""
    end_time = time.monotonic() + timeout_seconds
    while True:
        response = wait_for_response(
            responses,
            transaction_id,
            operation,
            max(0.1, end_time - time.monotonic()),
        )
        code = response.get("code")
        if code in {200, 400, 422, 500}:
            return response
        logger.info("Received non-terminal response code %s", code)


def require_response_code(response: dict[str, Any], expected_code: int) -> None:
    """Raise if a file-agent response did not return the expected code."""
    code = response.get("code")
    if code != expected_code:
        raise RuntimeError(
            f"Unexpected response code {code}: {response.get('message', '')}"
        )
    logger.info("Response accepted: code=%s message=%s", code, response.get("message"))


def parse_args(argv: Optional[list[str]] = None) -> DeviceDemoConfig:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint", help="IoT MQTT device data endpoint hostname.")
    parser.add_argument("username", help="MQTT username.")
    parser.add_argument("password", help="MQTT password.")
    parser.add_argument(
        "--client-id",
        help="MQTT client identifier. Defaults to the username.",
    )
    parser.add_argument(
        "--command-topic",
        default=DEFAULT_COMMAND_TOPIC,
        help=f"MQTT command topic. Default: {DEFAULT_COMMAND_TOPIC}",
    )
    parser.add_argument(
        "--response-topic",
        default=DEFAULT_RESPONSE_TOPIC,
        help=f"MQTT response topic. Default: {DEFAULT_RESPONSE_TOPIC}",
    )
    parser.add_argument(
        "--transaction-id",
        default=f"demo-{uuid.uuid4().hex}",
        help="Upload transaction id.",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=10,
        dest="ttl_minutes",
        help="Requested upload URL TTL in minutes.",
    )
    parser.add_argument(
        "--command",
        default="demo",
        help="file-agent command alias to request after upload.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        dest="file_path",
        help="Local file to upload. Defaults to a generated test file.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        dest="timeout_seconds",
        help="Timeout in seconds for MQTT responses and HTTP upload.",
    )
    args = parser.parse_args(argv)

    return DeviceDemoConfig(
        endpoint=args.endpoint,
        username=args.username,
        password=args.password,
        client_id=args.client_id if args.client_id is not None else args.username,
        command_topic=args.command_topic,
        response_topic=args.response_topic,
        transaction_id=args.transaction_id,
        ttl_minutes=args.ttl_minutes,
        command=args.command,
        file_path=args.file_path,
        timeout_seconds=args.timeout_seconds,
    )


def main(argv: Optional[list[str]] = None) -> int:
    """Run the device demo command-line interface."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    try:
        return run_demo(parse_args(argv))
    except Exception:
        logger.exception("Device demo failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
