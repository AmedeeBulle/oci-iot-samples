#!/usr/bin/env python3
"""
Subscribe to the raw_data_in queue and print received messages.

Copyright (c) 2025 Oracle and/or its affiliates.
Licensed under the Universal Permissive License v 1.0 as shown at
https://oss.oracle.com/licenses/upl

DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.

Simple client to stream Raw Messages received by the IoT Platform.
This example focus on the usage of the Queues; for more information on
database connection, see the "Query DB" example.
"""
import argparse
import re
import sys
import traceback
from typing import Optional
import uuid

import config
import oracledb
import oracledb.plugins.oci_tokens


def db_connect() -> oracledb.Connection:
    """Establish and returns a database connection using the configured settings.

    Returns:
        oracledb.Connection: The database connection object.

    Raises:
        ValueError: If the connection string is invalid.
    """
    # Extract hostname, port, and service from the connect string
    m = re.match(r"tcps:(.*):(\d+)/([^?]*)(\?.*)?", config.db_connect_string)
    if not m:
        raise ValueError("Invalid connect string")
    hostname, port, service, _ = m.groups()

    # Construct DSN for connection
    dsn = f"""
        (DESCRIPTION =
            (ADDRESS=(PROTOCOL=TCPS)(PORT={port})(HOST={hostname}))
            (CONNECT_DATA=(SERVICE_NAME={service}))
        )"""

    # Parameters for OCI token-based authentication
    token_based_auth = {
        "auth_type": config.oci_auth_type,
        "scope": config.db_token_scope,
    }
    if config.oci_auth_type == "ConfigFileAuthentication":
        token_based_auth["profile"] = config.oci_profile

    extra_connect_params = {}
    if config.thick_mode:
        print("Using oracledb Thick mode")
        oracledb.init_oracle_client(lib_dir=config.lib_dir, config_dir=".")
        extra_connect_params["externalauth"] = True
    else:
        print("Using oracledb Thin mode")

    return oracledb.connect(
        dsn=dsn, extra_auth_params=token_based_auth, **extra_connect_params
    )


def db_disconnect(connection: oracledb.Connection) -> None:
    """Close the provided database connection.

    Args:
        connection (oracledb.Connection): The database connection to close.
    """
    connection.close()


def build_subscriber_rule(
    connection: oracledb.Connection,
    digital_twin_instance_id: Optional[str],
    display_name: Optional[str],
    endpoint: Optional[str],
) -> Optional[str]:
    rule = None
    with connection.cursor() as cursor:
        if display_name:
            cursor.execute(
                f"""
                    select dti.data.id
                    from {config.iot_domain_short_name}__iot.digital_twin_instances dti
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
            quoted_digital_twin_instance_id = cursor.callfunc(
                "dbms_assert.enquote_literal", str, [digital_twin_instance_id]
            )
            condition = f"tab.user_data.digital_twin_instance_id = {quoted_digital_twin_instance_id}"
            rule = f"{rule} and {condition}" if rule is not None else condition
        if endpoint:
            quoted_endpoint = cursor.callfunc(
                "dbms_assert.enquote_literal", str, [endpoint]
            )
            condition = f"tab.user_data.endpoint = {quoted_endpoint}"
            rule = f"{rule} and {condition}" if rule is not None else condition
    return rule


def subscribe(
    connection: oracledb.Connection,
    queue_name: str,
    digital_twin_instance_id: Optional[str],
    display_name: Optional[str],
    endpoint: Optional[str],
) -> Optional[oracledb.DbObject]:
    """Subscribe to the Oracle AQ queue and listens for messages.

    Args:
        connection (oracledb.Connection): The database connection.
        digital_twin_instance_id (Optional[str]): The digital twin instance OCID.
        endpoint (Optional[str]): The endpoint (topic) to filter messages on.
    """
    try:
        rule = build_subscriber_rule(
            connection=connection,
            digital_twin_instance_id=digital_twin_instance_id,
            display_name=display_name,
            endpoint=endpoint,
        )
    except Exception as err:
        print(f"Exception occurred while building rule: {err}", file=sys.stderr)
        traceback.print_exc()
        return None

    try:
        agent_type = connection.gettype("SYS.AQ$_AGENT")
        subscriber = agent_type.newobject()
        subscriber.NAME = f"aq_sub_{str(uuid.uuid4()).replace('-', '_')}"
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
    except Exception as err:
        print(
            f"Exception occurred while registering subscriber: {err}", file=sys.stderr
        )
        traceback.print_exc()
        return None
    return subscriber


def stream(
    connection: oracledb.Connection, queue_name: str, subscriber: oracledb.DbObject
) -> None:
    try:
        raw_data_in_type = connection.gettype(queue_name + "_TYPE")
        queue = connection.queue(name=queue_name, payload_type=raw_data_in_type)
        queue.deqOptions.mode = oracledb.DEQ_REMOVE
        queue.deqOptions.wait = 10
        queue.deqOptions.navigation = oracledb.DEQ_NEXT_MSG
        queue.deqOptions.consumername = subscriber.NAME

        print("Listening for messages")
        while True:
            message: Optional[oracledb.aq.MessageProperties] = queue.deqone()
            if message:
                print(f"\nOCID         : {message.payload.DIGITAL_TWIN_INSTANCE_ID}")
                print(f"Time received: {message.payload.TIME_RECEIVED}")
                print(f"Endpoint     : {message.payload.ENDPOINT}")
                content = message.payload.CONTENT.read()
                print(f"Content      : {(content.decode())}")
                connection.commit()
            else:
                print(".", end="", flush=True)
    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        print(f"\n--- An unexpected error occurred: {e} ---")
        traceback.print_exc()


def unsubscribe(
    connection: oracledb.Connection, queue_name: str, subscriber: oracledb.DbObject
) -> None:
    try:
        with connection.cursor() as cursor:
            cursor.callproc(
                "dbms_aqadm.remove_subscriber",
                keyword_parameters={
                    "queue_name": queue_name,
                    "subscriber": subscriber,
                },
            )
    except Exception as err:
        print(
            f"Exception occurred while unregistering subscriber: {err}", file=sys.stderr
        )
        traceback.print_exc()


def parse_args():
    """
    Parse command-line arguments for aq-sub.

    Usage:
      aq-sub [-h|--help] [--id ID | --display-name NAME] [--endpoint ENDPOINT]

    --id and --display-name are mutually exclusive.
    All parameters are optional. All values are strings.
    """
    parser = argparse.ArgumentParser(
        description="aq-sub: Subscribe to the raw messages stream from IoT Platform."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--id",
        type=str,
        help="The Digital Twin Instance OCID (mutually exclusive with --display-name).",
    )
    group.add_argument(
        "--display-name",
        type=str,
        help="The Digital Twin Instance display name (mutually exclusive with --id).",
    )
    parser.add_argument("--endpoint", type=str, help="The message endpoint (topic).")
    args = parser.parse_args()
    return args


def main():
    args = parse_args()
    connection = db_connect()
    queue_name = f"{config.iot_domain_short_name}__iot.raw_data_in".upper()
    subscriber = subscribe(
        connection=connection,
        queue_name=queue_name,
        digital_twin_instance_id=args.id,
        display_name=args.display_name,
        endpoint=args.endpoint,
    )
    if subscriber:
        stream(connection=connection, queue_name=queue_name, subscriber=subscriber)
        unsubscribe(connection=connection, queue_name=queue_name, subscriber=subscriber)
    db_disconnect(connection=connection)


if __name__ == "__main__":
    main()
