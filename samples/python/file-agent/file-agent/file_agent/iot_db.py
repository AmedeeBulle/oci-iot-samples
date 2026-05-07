#
# Oracle DB/AQ access for OCI IoT normalized data.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

"""Oracle DB/AQ access for OCI IoT normalized data."""

import logging
import queue
import re
from collections.abc import Callable
from typing import Any, Optional

import oracledb
import oracledb.plugins.oci_tokens
from pydantic import ValidationError

from .models import InboundMessage

logger = logging.getLogger(__name__)

InvalidMessageHandler = Callable[[str, ValidationError], None]


def db_connect(
    db_connect_string: str,
    db_token_scope: str,
    thick_mode: bool = False,
    lib_dir: Optional[str] = None,
    oci_auth_type: str = "ConfigFileAuthentication",
    oci_profile: Optional[str] = "DEFAULT",
) -> oracledb.Connection:
    """Connect to the IoT Platform database using OCI token authentication."""
    match = re.match(r"tcps:(.*):(\d+)/([^?]*)(\?.*)?", db_connect_string)
    if not match:
        raise ValueError("Invalid connect string")
    hostname, port, service, _ = match.groups()
    dsn = f"""
        (DESCRIPTION =
            (ADDRESS=(PROTOCOL=TCPS)(PORT={port})(HOST={hostname}))
            (CONNECT_DATA=(SERVICE_NAME={service}))
        )"""

    token_based_auth = {
        "auth_type": oci_auth_type,
        "scope": db_token_scope,
    }
    if oci_auth_type in ["ConfigFileAuthentication", "SecurityToken"]:
        token_based_auth["profile"] = oci_profile or "DEFAULT"

    connect_kwargs = {}
    if thick_mode:
        oracledb.init_oracle_client(lib_dir=lib_dir, config_dir=".")
        connect_kwargs["externalauth"] = True

    return oracledb.connect(
        dsn=dsn,
        extra_auth_params=token_based_auth,
        **connect_kwargs,
    )


def db_disconnect(connection: oracledb.Connection) -> None:
    """Close a database connection."""
    connection.close()


def build_subscriber_rule(
    connection: oracledb.Connection,
    iot_domain_short_id: str,
    digital_twin_instance_id: Optional[str],
    display_name: Optional[str],
    content_path: Optional[str],
) -> Optional[str]:
    """Build a normalized-data subscriber rule."""
    rule = None
    with connection.cursor() as cursor:
        if display_name:
            cursor.execute(
                f"""
                    select dti.data.id
                    from {iot_domain_short_id}__iot.digital_twin_instances dti
                    where dti.data."displayName" = :display_name
                    and dti.data."lifecycleState" = 'ACTIVE'
                    order by dti.data."timeUpdated" desc
                """,
                {"display_name": display_name},
            )
            row = cursor.fetchone()
            if row and row[0]:
                digital_twin_instance_id = row[0]
            else:
                raise ValueError(f"No such display name: {display_name}")

        if digital_twin_instance_id:
            quoted_instance_id = cursor.callfunc(
                "dbms_assert.enquote_literal",
                str,
                [digital_twin_instance_id],
            )
            condition = f'tab.user_data."digitalTwinInstanceId" = {quoted_instance_id}'
            rule = f"{rule} and {condition}" if rule is not None else condition

        if content_path:
            quoted_content_path = cursor.callfunc(
                "dbms_assert.enquote_literal",
                str,
                [content_path],
            )
            condition = f'tab.user_data."contentPath" = {quoted_content_path}'
            rule = f"{rule} and {condition}" if rule is not None else condition

    logger.debug("Queue rule is: %s", rule)
    return rule


def add_subscriber(
    connection: oracledb.Connection,
    queue_name: str,
    subscriber_name: str,
    rule: Optional[str],
) -> None:
    """Register a normalized-data queue subscriber."""
    agent_type = connection.gettype("SYS.AQ$_AGENT")
    subscriber = agent_type.newobject()
    subscriber.NAME = subscriber_name
    subscriber.ADDRESS = None
    subscriber.PROTOCOL = 0
    with connection.cursor() as cursor:
        cursor.callproc(
            "dbms_aqadm.add_subscriber",
            keyword_parameters={
                "queue_name": queue_name,
                "subscriber": subscriber,
                "rule": rule,
                "transformation": None,
                "queue_to_queue": False,
                "delivery_mode": oracledb.MSG_PERSISTENT_OR_BUFFERED,
            },
        )


def remove_subscriber(
    connection: oracledb.Connection,
    queue_name: str,
    subscriber_name: str,
) -> None:
    """Remove a normalized-data queue subscriber."""
    agent_type = connection.gettype("SYS.AQ$_AGENT")
    subscriber = agent_type.newobject()
    subscriber.NAME = subscriber_name
    subscriber.ADDRESS = None
    subscriber.PROTOCOL = 0
    with connection.cursor() as cursor:
        cursor.callproc(
            "dbms_aqadm.remove_subscriber",
            keyword_parameters={
                "queue_name": queue_name,
                "subscriber": subscriber,
            },
        )


def dequeue_messages(
    connection: oracledb.Connection,
    queue_name: str,
    subscriber_name: str,
    iot_domain_short_id: str,
    message_queue: queue.Queue,
    invalid_message_handler: Optional[InvalidMessageHandler] = None,
    max_messages: Optional[int] = None,
) -> None:
    """Dequeue normalized IoT messages and forward valid file-agent requests."""
    db_queue = connection.queue(name=queue_name, payload_type="JSON")
    db_queue.deqOptions.mode = oracledb.DEQ_REMOVE
    db_queue.deqOptions.wait = 10
    db_queue.deqOptions.navigation = oracledb.DEQ_FIRST_MSG
    db_queue.deqOptions.consumername = subscriber_name

    processed = 0
    while max_messages is None or processed < max_messages:
        message = db_queue.deqone()
        if message is None:
            if max_messages is None:
                continue
            break

        processed += 1
        logger.info("Received message ID: %s", message.msgid.hex())
        connection.commit()
        try:
            inbound_message = InboundMessage.model_validate(message.payload)
        except ValidationError as exc:
            logger.error("Invalid message dequeued: %s", exc)
            instance_id = _payload_instance_id(message.payload)
            if instance_id and invalid_message_handler:
                invalid_message_handler(instance_id, exc)
            continue

        inbound_message.message_id = message.msgid.hex()
        display_name = resolve_display_name(
            connection,
            iot_domain_short_id,
            inbound_message.digital_twin_instance_id,
        )
        if display_name:
            inbound_message.digital_twin_display_name = display_name

        message_queue.put(inbound_message)


def resolve_display_name(
    connection: oracledb.Connection,
    iot_domain_short_id: str,
    digital_twin_instance_id: str,
) -> Optional[str]:
    """Resolve a Digital Twin display name for logging and command payloads."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
                select dti.data."displayName"
                from {iot_domain_short_id}__iot.digital_twin_instances dti
                where dti.data.id = :instance_id
            """,
            {"instance_id": digital_twin_instance_id},
        )
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
    return None


def _payload_instance_id(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        value = payload.get("digitalTwinInstanceId")
        if isinstance(value, str):
            return value
    return None
