# OCI IoT Platform: File Upload Sample

This demonstrates file uploads from an IoT device, represented by a Digital Twin
Instance (DTI), to OCI Object Storage using the OCI IoT Platform as the communication channel.

This is a simple demo application, not a production-ready file transfer service.
A production deployment should add stricter authorization and error handling,
durable state for queued or in-flight work, and database-backed recovery so
application failures do not lose accepted device requests or processing state.

## High-Level Workflow

![file-agent workflow](./images/file-agent.png)

1. Device: publish a request to the IoT Platform to prepare an upload.
1. File agent: consume the normalized DTI message from the IoT database (DB/AQ).
1. File agent: create an OCI Object Storage Pre-Authenticated Request (PAR) and
   send the upload URL to the device using an OCI IoT raw command.
1. Device: upload file(s) directly to Object Storage.
1. Device: publish a message to indicate that the upload is complete.
1. File agent: delete the PAR.
1. File agent: run optional post-processing.
1. File agent: notify the device of post-processing completion.

Command post-processing is queued in the file agent and runs asynchronously.

## Message Protocol

From the device perspective, the protocol uses MQTT JSON messages. The file
agent consumes device requests from the OCI IoT Platform normalized_data queue using
DB/AQ and sends responses back to the device using OCI IoT raw commands.

Default endpoints:

- Request topic: `iot/v1/file/cmd` -- the device publishes requests here, and
  the Digital Twin Adapter route maps these messages to `file.commandDetails`.
- Response endpoint: `iot/v1/file/rsp` -- the file agent sends raw-command
  responses here, and the device subscribes to this MQTT topic.

Messages use the following format:

```jsonc
{
  "op": "operation",
  "id": "transaction unique ID",
  "data": {
    // Operation-specific data
  },
  "code": 200, // Response code (only in response messages)
  "message": "message" // Response text (only in response messages)
}
```

### Prepare Upload

The device asks the file agent to prepare an upload and provides a unique ID for the
transaction. The request can also include the expected upload URL TTL in minutes.

```json
{
  "op": "prepare-upload",
  "id": "transaction unique ID",
  "data": {
    "ttl": 60
  }
}
```

Notes:

- All uploads will go to the same bucket (configurable)
- For security reasons, upload URLs are ephemeral and the TTL is capped at a
  configurable maximum value

### Upload Preparation

The file agent:

- Creates a write-only PAR for `<bucket>/<digital twin instance OCID>/<id>/`
- Sends the upload URL to the device. The URL includes the assigned upload
  directory because the device does not know its Digital Twin Instance OCID.

```json
{
  "op": "prepare-upload",
  "id": "transaction unique ID",
  "data": {
    "upload_url": "upload url with assigned directory"
  },
  "code": 200,
  "message": "Upload prepared"
}
```

If an error occurs while preparing the upload:

```json
{
  "op": "prepare-upload",
  "id": "transaction unique ID",
  "data": {},
  "code": 500,
  "message": "error message"
}
```

### Upload

The device:

- Uploads file(s)
- Informs the file agent with an optional command to run:

```jsonc
{
  "op": "complete-upload",
  "id": "transaction unique ID",
  "data": {
    "command": "command name", // Alias for the command to run (optional)
    "parameters": {
      "artifacts": [ "artifact" ]
    }
  }
}
```

If the device is unable to upload or wants to abort the upload transaction, it
should still send a `complete-upload` message to release the PAR.

### Process Artifacts

The file agent:

- Deletes the PAR
- Acknowledges the device
- Starts the processing command asynchronously

If there is a command:

```json
{
  "op": "complete-upload",
  "id": "transaction unique ID",
  "data": {},
  "code": 202,
  "message": "Process queued"
}
```

```json
{
  "op": "complete-upload",
  "id": "transaction unique ID",
  "data": {},
  "code": 201,
  "message": "Process started"
}
```

When processing completes (or when no processing was required):

```json
{
  "op": "complete-upload",
  "id": "transaction unique ID",
  "data": {},
  "code": 200,
  "message": "Process completed"
}
```

Appropriate error messages are sent when:

- No prepared upload exists for this `id`
- Invalid command
- Validation fails or an OCI service call fails

### Janitor

A separate janitor tool lists and optionally prunes leftover PARs, for example
when a device never completes an upload.

## OCI IoT Platform Resources

The [file_agent](./DTDL/file_agent_model.json) model describes the `commandDetails`
object expected by the file agent.

To enable the file upload capability, a digital twin model must include this
model as a component, for example:

```json
    {
      "@type": "Component",
      "name": "file",
      "schema": "dtmi:com:oracle:iot:fileagent;1",
      "displayName": "File Upload Component"
    }
```

A device adapter route must map the device payload to that component, for
example:

```json
    "payloadMapping": {
      "$.file.commandDetails": "${ {\"op\": .op, \"id\": .id, \"data\": .data } }"
    }
```

In the OCI IoT Platform, the _Content Path_ for normalized and historized data is
the component name from the device model (`file`) joined with the object name from the
file agent model (`commandDetails`). In this sample, that content path is
`file.commandDetails`.

This project provides a sample [_uploader_](./DTDL/uploader_model.json) model
and adapter ([envelope](./DTDL/uploader_adapter_envelope.json),
[routes](./DTDL/uploader_adapter_routes.json)) for demonstration purposes.

Create the IoT resources:

```shell
# Create the file agent model
oci iot digital-twin-model create \
  --display-name "file-agent-interface" \
  --description "File Agent interface" \
  --iot-domain-id "ocid1.iotdomain.oc1.<region>..." \
  --spec file://DTDL/file_agent_model.json

# Create the demo model and adapter
oci iot digital-twin-model create \
  --display-name "file-uploader" \
  --description "File uploader demo" \
  --iot-domain-id "ocid1.iotdomain.oc1.<region>..." \
  --spec file://DTDL/uploader_model.json

oci iot digital-twin-adapter create \
  --display-name "file-uploader" \
  --description "File uploader demo" \
  --iot-domain-id "ocid1.iotdomain.oc1.<region>..." \
  --digital-twin-model-spec-uri "dtmi:com:oracle:iot:uploader;1" \
  --inbound-envelope file://DTDL/uploader_adapter_envelope.json \
  --inbound-routes file://DTDL/uploader_adapter_routes.json

# Create the Digital Twin Instance.
# For simplicity, this example uses secret-based authentication.
oci iot digital-twin-instance create \
  --display-name "uploader-01" \
  --description "File Uploader 01" \
  --iot-domain-id "ocid1.iotdomain.oc1.<region>..." \
  --digital-twin-adapter-id "ocid1.iotdigitaltwinadapter.oc1.<region>..." \
  --external-key "uploader-01" \
  --auth-id "ocid1.vaultsecret.oc1.<region>..."
```

## File Agent

### Installation

Use Python 3.12 or higher. From the repository root, create and activate a
virtual environment, then install the file agent package:

```shell
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./file-agent
file-agent --help
```

To install the optional test dependencies and run the test suite:

```shell
python -m pip install -e './file-agent[test]'
python -m pytest -v file-agent/tests
```

### Configuration

Use [`file-agent-config.yaml`](./file-agent-config.yaml) as a template and
update it for the target OCI IoT domain and Object Storage bucket.

- `oci`: OCI authentication settings. Supported values are
  `ConfigFileAuthentication`, `InstancePrincipal`, and `SecurityToken`.
- `iot`: IoT domain OCID, queue subscriber, content path, and raw-command
  response endpoint settings. The domain short ID, database connect string, and
  database token scope are derived from the IoT domain and its parent domain
  group at startup.
- `object_storage`: upload bucket, optional namespace, maximum PAR TTL, and PAR
  name prefix.
- `commands`: optional command aliases mapped to absolute executable paths.
- `oracledb`: optional local Oracle Database driver settings, such as Thick mode.

The file agent typically runs on an OCI Compute Instance and authenticates using
Instance Principal. See the
[Connecting Directly to the IoT Database](https://docs.oracle.com/en-us/iaas/Content/internet-of-things/connect-database.htm)
scenario for more details.

### Running

Create the normalized-data queue subscriber:

```shell
file-agent --config-file file-agent-config.yaml subscribe
```

Run the monitor:

```shell
file-agent --config-file file-agent-config.yaml monitor
```

Remove the subscriber:

```shell
file-agent --config-file file-agent-config.yaml unsubscribe
```

List and prune leftover PARs:

```shell
file-agent --config-file file-agent-config.yaml janitor list
file-agent --config-file file-agent-config.yaml janitor prune \
  --min-age-minutes 60
```

## Device Demo

The `file-agent-device-demo` command simulates a device over MQTT. It connects
to the IoT MQTT device-data endpoint using TLS on port `8883`, with MQTT
`clean_session` disabled so the client uses a persistent session.

```shell
file-agent-device-demo \
  '<IoT device host>' \
  'mqtt-username' \
  'mqtt-password'
```

The demo publishes `prepare-upload`, uploads a generated test file to the
returned `upload_url`, then publishes `complete-upload` with the uploaded file
name in `data.parameters.artifacts`. It prints each MQTT, upload, and response
step at INFO level. By default it uses `iot/v1/file/cmd` for device commands,
`iot/v1/file/rsp` for responses, and the `demo` post-processing command alias.
