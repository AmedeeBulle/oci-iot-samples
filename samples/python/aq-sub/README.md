# Streaming IoT Platform data

This example demonstrates how to use
[Transactional Event Queues](https://www.oracle.com/database/advanced-queuing/)
to stream IoT Platform data.

You should already be familiar with connecting to the IoT Platform database.
If not, review the [Direct database connection example](../query-db/README.md)
in this repository.

The provided scripts allows you to subscribe to the raw and normalized message streams.

## Concepts

Digital Twin Instances data is available through data tables, but it can also be
streamed using the database Transactional Event Queues.

The following queues are available:

| Queue name       | Data type             | Description                      |
| ---------------- | --------------------- | -------------------------------- |
| raw_data_in      | raw_data_in_type      | Incoming raw messages            |
| raw_data_out     | raw_data_out_type     | Outgoing raw messages (commands) |
| normalized_data  | JSON                  | Normalized data                  |
| rejected_data_in | rejected_data_in_type | Rejected incoming messages       |

(See the
[Transactional Event Queues](https://docs.oracle.com/en-us/iaas/Content/internet-of-things/iot-domain-database-schema.htm#queues)
section of the IoT Platform documentation for detailed data type descriptions.)

Queue subscribers can be implemented a durable or non-durable:

- Durable subscribers: messages are kept in the queue until a client connects and read
  the messages.
  Note that the retention for IoT Platform queues is set to 24 hours.
- Non-durable subscribers: only returns the messages received while the client is
  connected.
  The Python SDK does not support non-durable subscribers as such, but this can be
  emulated by registering an ephemeral subscriber when a client connects.

Two sample scrips are provided:

- `aq-sub`: stream all incoming raw data (ADT -- Abstract Data Type). It is implement
  as a non-durable subscriber.
- `stream-normalized`: stream the normalized data (JSON), using a durable subscriber.

More information on the Python SDK is available on
[Using Oracle Transactional Event Queues and Advanced Queuing](https://python-oracledb.readthedocs.io/en/stable/user_guide/aq.html)

## Prerequisites

Install the Python dependencies.  
(Using a [Python virtual environment](https://docs.python.org/3/library/venv.html) is recommended):

```sh
pip install -r requirements.txt
```

When using `oracledb` in _Thick_ mode, the
[Oracle Instant Client](https://www.oracle.com/europe/database/technologies/instant-client.html)
must be installed (the 23ai Release Update or newer is recommended).
The `sqlnet.ora` parameter `SSL_SERVER_DN_MATCH` must also be set to `true`.

## Configure and run the script

Copy `config.distr.py` to `config.py` and set the following variables:

- `db_connect_string`: The `dbConnectionString` property of your IoT Domain Group.
- `db_token_scope`: The `dbTokenScope` property of your IoT Domain Group.
- `iot_domain_short_name`: The hostname part of the `deviceHost` property of your IoT Domain.
- `oci_auth_type`: The OCI authentication type. Use "ConfigFileAuthentication"
  for API key authentication, or "InstancePrincipal".
- `oci_profile`: OCI CLI profile to use for token retrieval (API key authentication only).
- `thick_mode`: Set to `True` to use the `oracledb` thick mode driver.

Run the script. Without parameter, it will show all messages.
You can filter by Digital Twin Instance OCID, display name, or endpoint (MQTT topic).

```text
$ ./aq-sub.py --help
usage: aq-sub.py [-h] [--id ID | --display-name DISPLAY_NAME] [--endpoint ENDPOINT]

aq-sub: Subscribe to the raw messages stream from IoT Platform.

options:
  -h, --help            show this help message and exit
  --id ID               The Digital Twin Instance OCID (mutually exclusive with --display-name).
  --display-name DISPLAY_NAME
                        The Digital Twin Instance display name (mutually exclusive with --id).
  --endpoint ENDPOINT   The message endpoint (topic).
```

The `stream-normalized` script is similar, but provides additional commands to manage
the durable subscription:

```text
$ ./stream-normalized --help
Usage: stream-normalized [OPTIONS] COMMAND [ARGS]...

  Stream Digital Twin normalized data.

  This example illustrate the use of "durable subscribers": once the
  subscriber has been created, messages are retained and returned when the
  client connects.

Options:
  --help  Show this message and exit.

Commands:
  stream       Stream data.
  subscribe    Subscribe to the normalized queue.
  unsubscribe  Unsubscribe to the normalized queue.
```
