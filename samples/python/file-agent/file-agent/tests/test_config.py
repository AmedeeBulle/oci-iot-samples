#
# Tests for file-agent configuration loading.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

import io
from pathlib import Path

import pytest
from pydantic import ValidationError

from file_agent.config import AppConfig, load_config


def _config_yaml(**overrides):
    config = {
        "oci": {"auth_type": "InstancePrincipal"},
        "iot": {
            "domain_id": "ocid1.iotdomain.oc1.eu-frankfurt-1.example",
            "subscriber_name": "file_agent",
            "digital_twin": {},
        },
        "object_storage": {
            "namespace_name": "namespace",
            "bucket_name": "uploads",
            "max_ttl_minutes": 45,
        },
        "commands": {"demo": "/opt/demo.sh"},
    }
    config.update(overrides)
    return config


def test_load_config_reads_yaml_file_like_object():
    config_file = io.StringIO("""
oracledb:
  thick_mode: true
  thick_mode_lib_dir: /opt/oracle/instantclient
oci:
  auth_type: InstancePrincipal
iot:
  domain_id: ocid1.iotdomain.oc1.eu-frankfurt-1.example
  subscriber_name: file_agent
  digital_twin: {}
object_storage:
  namespace_name: namespace
  bucket_name: uploads
commands:
  demo: /opt/demo.sh
""")

    config = load_config(config_file)

    assert config.object_storage.max_ttl_minutes == 60
    assert config.iot.response_endpoint == "iot/v1/file/rsp"
    assert config.iot.domain_id == "ocid1.iotdomain.oc1.eu-frankfurt-1.example"
    assert config.oracledb.thick_mode is True
    assert config.oracledb.thick_mode_lib_dir == "/opt/oracle/instantclient"
    assert config.commands == {"demo": "/opt/demo.sh"}


def test_load_config_allows_absent_oracledb_section():
    config_file = io.StringIO("""
oci:
  auth_type: InstancePrincipal
iot:
  domain_id: ocid1.iotdomain.oc1.eu-frankfurt-1.example
  subscriber_name: file_agent
  digital_twin: {}
object_storage:
  namespace_name: namespace
  bucket_name: uploads
""")

    config = load_config(config_file)

    assert config.oracledb.thick_mode is False
    assert config.oracledb.thick_mode_lib_dir is None


def test_checked_in_config_template_loads_with_default_oci_auth():
    repo_root = Path(__file__).resolve().parents[2]
    template = (repo_root / "file-agent-config.yaml").read_text(encoding="utf-8")
    config_file = io.StringIO(
        template.replace(
            "ocid1.iotdomain.oc1.<region>...",
            "ocid1.iotdomain.oc1.eu-frankfurt-1.example",
        )
        .replace("Object Storage namespace", "namespace")
        .replace("Upload bucket", "uploads")
    )

    config = load_config(config_file)

    assert config.oci.auth_type == "InstancePrincipal"


def test_load_config_treats_null_oci_section_as_defaults():
    config_file = io.StringIO("""
oci:
iot:
  domain_id: ocid1.iotdomain.oc1.eu-frankfurt-1.example
  subscriber_name: file_agent
  digital_twin: {}
object_storage:
  namespace_name: namespace
  bucket_name: uploads
""")

    config = load_config(config_file)

    assert config.oci.auth_type == "InstancePrincipal"


def test_digital_twin_filter_accepts_only_one_identifier():
    raw_config = _config_yaml(
        iot={
            "domain_id": "ocid1.iotdomain.oc1.eu-frankfurt-1.example",
            "subscriber_name": "file_agent",
            "digital_twin": {
                "instance_id": "ocid1.iotdigitaltwininstance.oc1..example",
                "display_name": "device-1",
            },
        }
    )

    with pytest.raises(ValidationError, match="Only one of"):
        AppConfig.model_validate(raw_config)


def test_object_storage_ttl_must_be_positive():
    raw_config = _config_yaml(
        object_storage={
            "namespace_name": "namespace",
            "bucket_name": "uploads",
            "max_ttl_minutes": 0,
        }
    )

    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw_config)
