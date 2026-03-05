# Sending observed time in device payload

## The `timeObserved` property

Digital twins with telemetry in structured format will by default set the Time Observed
property to the time the payload was received.

You can override this with data from the payload by assigning the `timeObserved` property
in the envelope mapping section of the digital twin adapter envelope.

If a default adapter is used, the generated envelope will already contain a mapping:

```json
"envelopeMapping": {
    "timeObserved": "$.time"
}
```

This means that if a `time` field is present in the payload, it will be used as the
observed time; if not, it will default to the received time.

## Data format

The `timeObserved` property supports two input formats in payload mappings:

1. POSIX/Epoch time in microseconds (integer): number of microseconds elapsed since
   January 1, 1970 00:00:00 UTC.
2. UTC timestamp string with microseconds: `YYYY-MM-DDTHH:MM:SS.ffffffZ`.

The following sample payload (from the [publish-mqtt](../../python/publish-mqtt/)
example) uses option 1 and sets the observed time to:
Wednesday, September 10, 2025 13:47:05.226854 UTC:

```json
{
    "time": 1757512025226854,
    "sht_temperature": 23.8,
    "qmp_temperature": 24.4,
    "humidity": 56.1,
    "pressure": 1012.2,
    "count": 1,
}
```

The following payload uses option 2 with an RFC3339/ISO-8601 UTC string:

```json
{
    "time": "2025-09-10T13:47:05.226854Z",
    "sht_temperature": 23.8,
    "qmp_temperature": 24.4,
    "humidity": 56.1,
    "pressure": 1012.2,
    "count": 1,
}
```

## Conversion

If the device sends a date string in a different format, it must be converted in the
envelope mapping.

The IoT Platform mappings can be done with JsonPath or JQ expression. To facilitate the
conversion of a date string to POSIX time format, the Platform provides an additional
JQ function: `fromdateformat`

To accept a payload in a non-native format such as:

```json
{
    "iso_time": "2025/09/10 13:47:05.226854",
    "sht_temperature": 23.8,
    ...
}
```

we can use the following envelope mapping:

```json
"envelopeMapping": {
    "timeObserved": "${.iso_time | fromdateformat(\"yyyy/MM/dd HH:mm:ss.SSSSSS\")}"
}
```

The patterns used for parsing are compatible with the [Java DateTimeFormatter](https://docs.oracle.com/en/java/javase/23/docs/api/java.base/java/time/format/DateTimeFormatter.html#patterns).

Note that such conversion might fail if the payload field (`iso_time` in this case) is missing
from the payload, as the function might not accept a null value.
If the field is optional, null values should be handled in the expression. For example:

```json
"envelopeMapping": {
    "timeObserved": "${if .iso_time == null then null else .iso_time | fromdateformat(\"yyyy-MM-dd'T'HH:mm:ss.SSSSSS'Z'\") end}"
}
```
