# Direct database connection

The OCI Internet of Things Platform allows you to connect directly to the
database that stores your Digital Twin metadata and telemetry data.

This guide shows how to connect to the IoT Platform database using
[Oracle SQLcl](https://www.oracle.com/database/sqldeveloper/technologies/sqlcl/).

## What is in the IoT database?

When you connect to the IoT Platform database, there are two schema contexts
to keep in mind:

- `<DomainShortId>__IOT`  
  Read-only schema for IoT domain metadata and telemetry data.

  Use `<DomainShortId>__IOT` to query:
  - Digital Twin metadata, such as models, adapters, instances, and relationships
  - telemetry-related tables and views, such as raw, historized, rejected, and
    command-related data
  - Transactional Event Queues (TxEventQ), including:
    - `RAW_DATA_IN` for inbound raw device payloads
    - `REJECTED_DATA_IN` for inbound payloads that were rejected, including
      reason code and reason message
    - `NORMALIZED_DATA` for normalized telemetry values keyed by digital twin
      instance, content path, value, and time observed

  For the authoritative `<DomainShortId>__IOT` schema reference, including the
  JSON collections, data tables, and queues it contains, see
  [IoT Domain Database Schema Reference](https://docs.oracle.com/en-us/iaas/Content/internet-of-things/iot-domain-database-schema.htm#data-tables).

- `<DomainShortId>__WKSP`  
  Read/write workspace schema.

  Use `<DomainShortId>__WKSP` for workspace-owned objects and for development
  work that requires write access.

The `DomainShortId` is the hostname prefix of the IoT Domain Device Host and
can be retrieved with:

```shell
iot_domain_id="<IoT Domain OCID>"
oci iot domain get --iot-domain-id "${iot_domain_id}" |
  jq -r '.data."device-host" | split(".")[0]'
```

The names of `<DomainShortId>__IOT` and `<DomainShortId>__WKSP` can also be
found on the IoT Domain page in the OCI Console.

## Prerequisites

- Your client VCN must be included in the Allow List defined at the IoT
  Domain Group level.
- Database authentication is handled by
  [OCI Identity Database Tokens](https://docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/iam-access-database.html#GUID-CFC74EAF-E887-4B1F-9E9A-C956BCA0BEA9).  
  To retrieve a valid token, the requester must be part of one of the identity
  groups listed at the IoT Domain level.
  The OCI IoT Platform supports *Instance Principal* authentication; that is,
  the identity group can be a *Dynamic Group*.

See
[Scenario: Connecting Directly to the IoT Database](https://docs.oracle.com/en-us/iaas/Content/internet-of-things/connect-database.htm)
for more details.

## Connecting to the database

To install the OCI CLI and SQLcl on Oracle Linux 9, run:

```bash
sudo dnf install -y sqlcl jdk-25-headless python39-oci-cli
```

For the `oci` command:

- API key authentication: add the `--profile` option to use a non-default
  profile, or set `OCI_CLI_PROFILE=<your profile>` in your environment.
- Instance principal authentication: use `--auth instance_principal`, or set
  `OCI_CLI_AUTH=instance_principal` in your environment.

### Connect with an IAM database token

Obtain the database token scope and retrieve a token:

```shell
# Retrieve scope
iot_domain_group_id="<IoT Domain Group OCID>"
iot_db_token_scope=$(
  oci iot domain-group get --iot-domain-group-id "${iot_domain_group_id}" \
   --query 'data."db-token-scope"' --raw-output
)

# Get token (valid for 60 minutes)
oci iam db-token get --scope "${iot_db_token_scope}"
```

Obtain the JDBC connect string and connect to the database:

```shell
iot_db_connect_string=$(
  oci iot domain-group get --iot-domain-group-id "${iot_domain_group_id}" \
  --query 'data."db-connection-string"' --raw-output
)

sql "/@jdbc:oracle:thin:@${iot_db_connect_string}&TOKEN_AUTH=OCI_TOKEN"
```

By default, this connects you as a global database user, not directly into
either `<DomainShortId>__IOT` or `<DomainShortId>__WKSP`.

## Proxy into the workspace schema

If you want to start your SQLcl session directly in `<DomainShortId>__WKSP`,
you can reuse the same IAM database token and proxy into that schema:

```shell
sql "jdbc:oracle:thin:[<DomainShortId>__WKSP]/@${iot_db_connect_string}&TOKEN_AUTH=OCI_TOKEN"
```

This keeps IAM token authentication enabled while starting the Autonomous
Database session in the `<DomainShortId>__WKSP` schema context.

## Running queries against the IoT schema

The sample telemetry queries below target the read-only
`<DomainShortId>__IOT` schema.

If you connected as the default global user, or if you proxied into
`<DomainShortId>__WKSP`, you can either:

- qualify object names explicitly, or
- switch the session context before running the examples:

```sql
alter session set current_schema = <DomainShortId>__IOT;
```

## Sample SQL sessions

Select raw messages received in the last 5 minutes. Join with Digital Twin
instances to display device names. The query assumes that messages aren't
binary.

```sql
select
    dt.data.displayName,
    rd.time_received,
    rd.endpoint,
    utl_raw.cast_to_varchar2(dbms_lob.substr(rd.content, 40)) as content
from raw_data rd, digital_twin_instances dt
where rd.digital_twin_instance_id = dt.data."_id"
  and rd.time_received > sysdate - 1/24/12
order by rd.time_received;
```

Select historized messages observed in the last 5 minutes. The `value` column
is of JSON type.

```sql
select
    dt.data.displayName,
    hd.time_observed,
    hd.content_path,
    json_serialize (hd.value returning varchar2(40) truncate error on error) as value
from historized_data hd, digital_twin_instances dt
where hd.digital_twin_instance_id = dt.data."_id"
  and hd.time_observed > sysdate - 1/24/12
order by hd.time_observed;
```

Select rejected messages received in the last 5 minutes. The query assumes that
messages aren't binary.

```sql
select
    dt.data.displayName,
    rd.time_received,
    rd.endpoint,
    rd.reason_code,
    rd.reason_message,
    utl_raw.cast_to_varchar2(dbms_lob.substr(rd.content, 40)) as content
from rejected_data rd, digital_twin_instances dt
where rd.digital_twin_instance_id = dt.data."_id"
  and rd.time_received > sysdate - 1/24/12
order by rd.time_received;
```
