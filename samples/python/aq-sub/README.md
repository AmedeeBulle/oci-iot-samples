# Streaming IoT Platform data

This example demonstrates how to use
[Transactional Event Queues](https://www.oracle.com/database/advanced-queuing/)
to stream IoT Platform data.

You should already be familiar with connecting to the IoT Platform database.
If not, review the [Direct database connection example](../query-db/README.md)
in this repository.

The provided script allows you to subscribe to the raw messages stream.

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

(See
[documentation](https://docs.oracle.com/en-us/iaas/Content/internet-of-things/iot-domain-database-schema.htm#queues__rejected-data-queues)
for detailed data type descriptions.)

This sample script acts as a "non durable subscriber": it will  only receive messages
published while active and connected.
To retrieve messages published while disconnected, you should create a subscriber in a
separate process.
Keep in mind that the queues retention is set to 24 hours.

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

```sh
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
