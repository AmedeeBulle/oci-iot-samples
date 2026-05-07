# OCI IoT Platform microcontroller demo (M5Stack CoreS3)

## Introduction

Sample code to send telemetry data from a microcontroller (M5Stack CoreS3) to the Oracle
OCI IoT Platform using MQTT over TLS (MQTTS).

## Hardware platform

<!-- markdownlint-disable MD033 -->
<p align="center">
  <a href="./images/M5Stack-CoreS3.jpeg">
    <img src="./images/M5Stack-CoreS3.jpeg" alt="M5Stack CoreS3 with Env III sensor" width="300">
  </a>
</p>
<!-- markdownlint-enable MD033 -->

This project uses the [M5Stack CoreS3](https://docs.m5stack.com/en/core/CoreS3) platform
based on an [Espressif ESP32-S3](https://www.espressif.com/en/products/socs/esp32-s3) MCU.

Environmental data is collected with an [M5Stack ENV III](https://docs.m5stack.com/en/unit/envIII)
sensor which integrates:

- a [Sensirion SHT30](https://sensirion.com/products/catalog/SHT30-DIS-B)
  humidity and temperature sensor
- a [QST QMP6988](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/unit/enviii/QMP6988%20Datasheet.pdf)
  barometric pressure and temperature sensor

## Software environment

The project is written in C, using the
[Espressif IoT Development Framework](https://idf.espressif.com/) version 5.x.

To facilitate the interface with the hardware of the M5Stack CoreS3, we use the
[Board Support Package (BSP) for M5Stack CoreS3](https://components.espressif.com/components/espressif/m5stack_core_s3/versions/3.0.2/readme).
Note that the BSP uses the newer ESP_IDF i2c_master API (driver_ng);
The components used to retrieve sensor data are based on the
[esp-idf-lib/sht3x](https://components.espressif.com/components/esp-idf-lib/sht3x/versions/1.0.8/readme)
and [esp-idf-lib/qmp6988](https://components.espressif.com/components/esp-idf-lib/qmp6988/versions/0.0.6/readme)
components updated to use the i2c_master API.

## IoT Platform configuration

The device sends telemetry payloads in JSON format on `${topic}/telemetry`
(default base topic: `iot/v1`):

```json
{
  "time": "time since epoch in microseconds",
  "sht_temperature": "temperature measured with the SHT30 sensor (°C)",
  "qmp_temperature": "temperature measured with the QMP6988 sensor (°C)",
  "humidity": "relative humidity (%RH)",
  "pressure": "pressure (hPa)",
  "count": "message counter"
}
```

It also listens on `${topic}/cmd/<key>` for commands and responds on `${topic}/rsp/<key>`
(_Command-Response_ scenario).
Only the `ota` command is implemented (see below), for any other command,
the device will simply return an acknowledgment.

A sample IoT model and adapter are provided in the [config-iot](./config-iot/) directory.
The provided adapter files match the default base topic `iot/v1`. The device can use
a different base MQTT topic, but the adapter envelope `reference-endpoint`, adapter
route endpoint condition, command request endpoint, and command response endpoint must
be updated to use the same topic structure.

Create IoT model:

```shell
oci iot digital-twin-model create \
  --display-name "M5 CoreS3 Model" \
  --description "A device with environmental sensors" \
  --iot-domain-id "ocid1.iotdomain.oc1.my.domain.ocid..." \
  --spec file://config-iot/m5_cores3_model.json
```

Create IoT adapter:

```shell
oci iot digital-twin-adapter create \
  --iot-domain-id "ocid1.iotdomain.oc1.my.domain.ocid..." \
  --display-name "M5 CoreS3 Adapter" \
  --description "A digital twin adapter for the M5 CoreS3" \
  --digital-twin-model-spec-uri "dtmi:com:oracle:sample:m5:cores3;1" \
  --inbound-envelope file://config-iot/m5_cores3_adapter_envelope.json \
  --inbound-routes file://config-iot/m5_cores3_adapter_routes.json
```

Create either a Vault Secret or a Certificate to authenticate your device.

Create IoT Digital Twin Instance:

```shell
oci iot digital-twin-instance create \
  --display-name "M5 CoreS3" \
  --description "M5 CoreS3 device" \
  --iot-domain-id "ocid1.iotdomain.oc1.my.domain.ocid..." \
  --digital-twin-adapter-id "ocid1.iotdigitaltwinadapter.oc1.my.adapter.ocid..." \
  --external-key "user_name_or_certificate_cname" \
  --auth-id "secret_or_certificate_ocid"
```

## Build and install the firmware

Install the Espressif IoT Development Framework and run from the top of the project directory:

```bash
idf.py set-target esp32s3
idf.py build
idf.py flash
```

## Device configuration

### Configuration file

The device loads configuration from `oci-iot.ini` on the SD card at boot. If valid,
the configuration is stored in SPIFFS for subsequent boots.
The SD card is only needed when the configuration changes.

See the [`oci-iot.distr.ini`](./config-device/oci-iot.distr.ini) template for more details.

Minimal example:

```ini
; OCI IoT Platform demo - device configuration file
; Do NOT quote parameter values!

[config]
version = 1

[hardware]
; i2c_port = B
; display_brightness = 40
; display_timeout = 300

[wifi]
ssid =
password =

[mqtt]
host =
port = 8883
ca_cert = digicert-global-g2.pem
user =
password =
client_cert =
client_key =
qos = 0
keep_alive = 60
topic = iot/v1
publish_freq = 60

[ota]
; ca_cert =
```

### Certificates

Certificates referenced in the configuration must be present on the SD card.
On first boot, they are copied to SPIFFS.

- `mqtt.ca_cert` is required for MQTTS (port 8883). If omitted, the MQTT client fails
  closed and does not connect.
- `ota.ca_cert` is optional. If not provided, it defaults to the MQTT CA certificate.
  OTA updates require a CA certificate either way.

### Firmware updates

There are 3 possible options:

1. **Corded:** Flash the firmware with the `idf.py` or `esptool` utilities.
1. **SD card update:** If `oci-iot.bin` is present on the SD card at boot time,
   it is flashed, removed, and the device reboots.
1. **OTA update:** Send an MQTT command with `cmd = ota`, a `url` to the firmware, and
   the firmware `version`. The device downloads and applies the update, then reboots
   (see below for details).

### High level operational overview

At boot, the device:

1. Checks for a firmware update on the SD card.
1. Loads configuration and certificates.
1. Shows splash screen and initializes display/screensaver.
1. Connects to Wi-Fi and syncs time via SNTP.
1. Connects to MQTT.
1. Subscribes to `${topic}/cmd/+` for commands.
1. Publishes telemetry every `publish_freq` seconds to `${topic}/telemetry`.

<!-- markdownlint-disable MD033 -->
<p align="center">
  <img src="./images/M5Stack-CoreS3.gif" alt="M5Stack CoreS3 with Env III sensor" width="300">
</p>
<!-- markdownlint-enable MD033 -->

## OTA Updates

The IoT platform can be used to send OTA updates to the device.

Create an OCI Object Storage Bucket to store firmware as well as a
Pre-Authenticated Request (PAR) to expose it to the Internet.

Build a new firmware (`idf.py build`) and upload it to the bucket (can be any name):

  ```shell
  oci os object put \
    -bn bucket_name \
    --file ./build/oci-iot.bin \
    --name oci-iot-v0.1.0.bin
  ```

Note that the firmware version is derived from the latest `git` tag and hash.
You can check the version of your latest build with:

```shell
jq -r '.project_version' build/project_description.json
```

Send a command to the device using the following payload:

```json
{
    "cmd": "ota",
    "url": "<PAR URL>oci-iot-v0.1.0.bin",
    "version": "v0.1.0"
}
```

The `version` field is required and must be the version of the firmware at `url`.
The device skips the update when this value is equal to the running version.

Sample command line to trigger the OTA update:

```shell
oci iot digital-twin-instance invoke-raw-json-command \
    --digital-twin-instance-id "ocid1.iotdigitaltwininstance.oc1.my.dti.ocid..." \
    --request-endpoint "iot/v1/cmd/123" \
    --request-duration "PT10M" \
    --response-endpoint "iot/v1/rsp/123" \
    --response-duration "PT10M" \
    --request-data '{
        "cmd": "ota",
        "url": "<PAR URL>oci-iot-v0.1.0.bin",
        "version": "v0.1.0"
    }'
```

You can check the status of your request:

- By querying the `RAW_COMMAND_DATA` database table
- It is also available in the "OCI IoT Platform Explorer" APEX demo application
