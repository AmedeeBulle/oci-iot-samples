# Streaming IoT Platform Data With Java

This directory demonstrates how to use Oracle Database Transactional Event Queues
to stream Oracle Internet of Things Platform data from Java.

The samples connect to ATP using an OCI IAM database token obtained through the
OCI Java SDK. The JDBC connection uses the IoT `tcps:` connect string directly.

You should already be familiar with connecting to the IoT Platform database. If not,
review the direct database connection samples in this repository first.

## Concepts

Digital Twin Instance data is available through tables, but it can also be streamed
using database Transactional Event Queues.

The following queues are available in the IoT Platform schema:

| Queue name | Data type | Description |
|------------|-----------|-------------|
| `raw_data_in` | `raw_data_in_type` | Incoming raw messages |
| `raw_data_out` | `raw_data_out_type` | Outgoing raw messages (commands) |
| `normalized_data` | `JSON` | Normalized data |
| `rejected_data_in` | `rejected_data_in_type` | Rejected incoming messages |

The `normalized_data` queue is a JSON queue. The others use Oracle Abstract Data Types
for their payloads.

Queue subscribers can be implemented in a durable or non-durable way:

- Durable subscribers keep messages until a client connects and consumes them.
  The normalized Java sample uses this model.
- Non-durable subscribers only receive messages while the client is active.
  The raw Java sample emulates this by creating an ephemeral subscriber and removing it
  in the same session.

## Sample Applications

Two Java sample applications are provided:

- `QueueSubscriberApp`: manages and consumes the normalized JSON queue using a durable subscriber
- `RawQueueSubscriberApp`: streams the `raw_data_in` ADT queue using an ephemeral subscriber

The normalized sample demonstrates filtering by Digital Twin Instance OCID, display name,
or content path. The raw sample demonstrates filtering by Digital Twin Instance OCID,
display name, or endpoint.

## Prerequisites

- Java 17 or newer
- Maven
- Access to the target OCI tenancy and ATP database
- An OCI auth setup supported by the sample:
  - `ConfigFileAuthentication`
  - `SecurityToken`
  - `InstancePrincipal`

## Configuration

Copy `config.distr.properties` to `config.properties` and set the following values:

- `db.connect.string`
- `db.token.scope`
- `iot.domain.short.name`
- `oci.auth.type`
- `oci.profile`
- `oci.config.file`
- `subscriber.name`

`oci.config.file` can be left blank to use the default OCI config location `~/.oci/config`.
`subscriber.name` is used by the durable normalized queue sample.

## Build And Test

From the repository root:

```sh
mvn -q -f samples/java/queues/pom.xml test
```

## Run The Samples

### Normalized JSON Queue

Show help:

```sh
mvn -q -f samples/java/queues/pom.xml exec:java -Dexec.args="--help"
```

Create a durable subscriber:

```sh
mvn -q -f samples/java/queues/pom.xml exec:java -Dexec.args="subscribe --content-path temperature"
```

Create a subscriber filtered by Digital Twin Instance display name:

```sh
mvn -q -f samples/java/queues/pom.xml exec:java -Dexec.args="subscribe --display-name sensor-01 --content-path humidity"
```

Consume from the subscriber:

```sh
mvn -q -f samples/java/queues/pom.xml exec:java -Dexec.args="-v stream"
```

Delete the subscriber:

```sh
mvn -q -f samples/java/queues/pom.xml exec:java -Dexec.args="unsubscribe"
```

### Raw ADT Queue

Show help:

```sh
mvn -q -f samples/java/queues/pom.xml -Dexec.mainClass=com.oracle.iot.sample.queues.RawQueueSubscriberApp exec:java -Dexec.args="--help"
```

Stream from the raw ADT queue with an ephemeral subscriber:

```sh
mvn -q -f samples/java/queues/pom.xml -Dexec.mainClass=com.oracle.iot.sample.queues.RawQueueSubscriberApp exec:java -Dexec.args="-v"
```

Stream from the raw ADT queue filtered by endpoint:

```sh
mvn -q -f samples/java/queues/pom.xml -Dexec.mainClass=com.oracle.iot.sample.queues.RawQueueSubscriberApp exec:java -Dexec.args="--endpoint zigbee2mqtt/sensor-01"
```

If you want to point either sample at another config file:

```sh
mvn -q -f samples/java/queues/pom.xml exec:java -Dexec.args="--config /path/to/config.properties subscribe"
```

## Notes

- `subscribe` rejects `--id` and `--display-name` together.
- `stream` dequeues from the durable subscriber configured by `subscriber.name`.
- The raw sample also rejects `--id` and `--display-name` together.
- The raw sample uses a temporary subscriber name per run and removes it on exit.
- The samples include unit tests for config loading, direct JDBC URL handling,
  rule building, raw ADT helpers, and CLI validation.
- Live OCI and ATP verification still requires your environment and credentials.
