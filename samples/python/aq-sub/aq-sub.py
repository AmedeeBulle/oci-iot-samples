#!/usr/bin/env python3
"""
Subscribe to the raw_data_in queue and print received messages.

Copyright (c) 2025 Oracle and/or its affiliates.
Licensed under the Universal Permissive License v 1.0 as shown at
https://oss.oracle.com/licenses/upl

DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.

Simple client to stream Raw Messages received by the IoT Platform.
This example focus on the usage of the Queues; for more information on
database connection, see the "Query DQ" example.
"""
import argparse
import re
import traceback
from typing import Optional
import uuid

import config
import oracledb
import oracledb.plugins.oci_tokens


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


def get_digital_twin_instance_id(
    connection: oracledb.Connection, display_name: str
) -> Optional[str]:
    """
    Return the Digital Twin Instance ID based on the display_name.

    Args:
        connection: An oracledb.Connection object.
        display_name: The Digital Twin Instance ID display name.

    Returns:
        The digital twin instance ID, or None if not found.

    Note:
        The display name is not a unique attribute, if multiple digital twin instances
        have the same display name, the most recently updated is returned.
    """
    with connection.cursor() as cursor:
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
            return row[0]
        return None


def aq_subscribe(
    connection: oracledb.Connection,
    digital_twin_instance_id: Optional[str],
    endpoint: Optional[str],
) -> None:
    """Subscribe to the Oracle AQ queue and listens for messages.

    Args:
        connection (oracledb.Connection): The database connection.
        digital_twin_instance_id (Optional[str]): The digital twin instance OCID.
        endpoint (Optional[str]): The endpoint (topic) to filter messages on.
    """
    # Create subscriber
    queue_name = f"{config.iot_domain_short_name}__iot.raw_data_in".upper()
    consumer_name = f"aq_sub_{str(uuid.uuid4()).replace('-', '_')}"
    agent_type = connection.gettype("SYS.AQ$_AGENT")
    subscriber = agent_type.newobject()
    subscriber.NAME = consumer_name
    subscriber.ADDRESS = None
    subscriber.PROTOCOL = 0
    raw_data_in_type = connection.gettype(
        f"{config.iot_domain_short_name}__iot.raw_data_in_type".upper()
    )

    with connection.cursor() as cursor:
        rule = None
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

    try:
        queue = connection.queue(queue_name, raw_data_in_type)
        queue.deqOptions.mode = oracledb.DEQ_REMOVE
        queue.deqOptions.wait = 10
        queue.deqOptions.navigation = oracledb.DEQ_FIRST_MSG
        queue.deqOptions.consumername = consumer_name

        print("Listening for messages")
        while True:
            message = queue.deqone()
            if message:
                # print(f"ID     : {message.msgid}")
                print(f"\nOCID   : {message.payload.DIGITAL_TWIN_INSTANCE_ID}")  # type: ignore
                print(f"Topic  : {message.payload.ENDPOINT}")  # type: ignore
                content = message.payload.CONTENT.read()  # type: ignore
                print(f"Content: {(content.decode())}")
            else:
                print(".", end="", flush=True)
                pass

    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        print(f"\n--- An unexpected error occurred: {e} ---")
        traceback.print_exc()
    finally:
        with connection.cursor() as cursor:
            cursor.callproc(
                "dbms_aqadm.remove_subscriber",
                keyword_parameters={
                    "queue_name": queue_name,
                    "subscriber": subscriber,
                },
            )


def main():
    """Entry point for the aq-sub script."""
    args = parse_args()

    connection = db_connect()

    if args.display_name:
        digital_twin_instance_id = get_digital_twin_instance_id(
            connection=connection, display_name=args.display_name
        )
    elif args.id:
        digital_twin_instance_id = args.id
    else:
        digital_twin_instance_id = None

    try:
        aq_subscribe(
            connection=connection,
            digital_twin_instance_id=digital_twin_instance_id,
            endpoint=args.endpoint,
        )
    except Exception as e:
        print(f"\n--- An unexpected error occurred: {e} ---")
        traceback.print_exc()
    finally:
        db_disconnect(connection=connection)


if __name__ == "__main__":
    main()
