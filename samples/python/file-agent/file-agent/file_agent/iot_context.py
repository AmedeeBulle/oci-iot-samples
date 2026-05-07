#
# OCI IoT domain context derivation.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

"""OCI IoT domain context derivation."""

from dataclasses import dataclass

from oci import iot as oci_iot


@dataclass(frozen=True)
class IOTDomainContext:
    """Derived IoT domain settings used by DB/AQ access."""

    domain_short_id: str
    db_connection_string: str
    db_token_scope: str


def derive_iot_domain_context(
    iot_client: oci_iot.IotClient,
    iot_domain_id: str,
) -> IOTDomainContext:
    """Derive DB/AQ settings from an IoT domain OCID."""
    domain = iot_client.get_iot_domain(iot_domain_id=iot_domain_id).data
    device_host = _required_attr(domain, "device_host")
    domain_group_id = _required_attr(domain, "iot_domain_group_id")

    domain_group = iot_client.get_iot_domain_group(
        iot_domain_group_id=domain_group_id
    ).data
    db_connection_string = _required_attr(domain_group, "db_connection_string")
    db_token_scope = _required_attr(domain_group, "db_token_scope")

    return IOTDomainContext(
        domain_short_id=device_host.split(".", maxsplit=1)[0],
        db_connection_string=db_connection_string,
        db_token_scope=db_token_scope,
    )


def _required_attr(resource, attr_name: str) -> str:
    value = getattr(resource, attr_name, None)
    if not value:
        raise ValueError(f"Missing {attr_name} in OCI IoT response")
    return value
