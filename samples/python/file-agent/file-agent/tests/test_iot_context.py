#
# Tests for OCI IoT domain context derivation.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

from types import SimpleNamespace

import pytest

from file_agent.iot_context import derive_iot_domain_context


class _FakeIOTClient:
    def __init__(self, domain, domain_group):
        self.domain = domain
        self.domain_group = domain_group
        self.domain_ids = []
        self.domain_group_ids = []

    def get_iot_domain(self, iot_domain_id):
        self.domain_ids.append(iot_domain_id)
        return SimpleNamespace(data=self.domain)

    def get_iot_domain_group(self, iot_domain_group_id):
        self.domain_group_ids.append(iot_domain_group_id)
        return SimpleNamespace(data=self.domain_group)


def test_derive_iot_domain_context_reads_domain_and_parent_group():
    domain = SimpleNamespace(
        device_host="abc123.device.iot.eu-frankfurt-1.oci.oraclecloud.com",
        iot_domain_group_id="ocid1.iotdomaingroup.oc1..group",
    )
    domain_group = SimpleNamespace(
        db_connection_string="tcps:adb.example.com:1521/service",
        db_token_scope="urn:oracle:db::id::scope",
    )
    client = _FakeIOTClient(domain, domain_group)

    context = derive_iot_domain_context(
        iot_client=client,
        iot_domain_id="ocid1.iotdomain.oc1..domain",
    )

    assert client.domain_ids == ["ocid1.iotdomain.oc1..domain"]
    assert client.domain_group_ids == ["ocid1.iotdomaingroup.oc1..group"]
    assert context.domain_short_id == "abc123"
    assert context.db_connection_string == "tcps:adb.example.com:1521/service"
    assert context.db_token_scope == "urn:oracle:db::id::scope"


def test_derive_iot_domain_context_rejects_incomplete_domain_response():
    client = _FakeIOTClient(
        domain=SimpleNamespace(device_host="", iot_domain_group_id=""),
        domain_group=SimpleNamespace(),
    )

    with pytest.raises(ValueError, match="device_host"):
        derive_iot_domain_context(
            iot_client=client,
            iot_domain_id="ocid1.iotdomain.oc1..domain",
        )
