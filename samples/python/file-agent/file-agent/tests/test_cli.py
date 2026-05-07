#
# Tests for the file-agent CLI.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

from click.testing import CliRunner

import file_agent.cli as cli_module
from file_agent.cli import cli


def test_cli_exposes_expected_commands():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "subscribe" in result.output
    assert "unsubscribe" in result.output
    assert "monitor" in result.output
    assert "janitor" in result.output


def _write_config(tmp_path):
    config_path = tmp_path / "file-agent.yaml"
    config_path.write_text(
        """
oracledb:
  thick_mode: false
oci:
  auth_type: InstancePrincipal
iot:
  domain_id: ocid1.iotdomain.oc1.eu-frankfurt-1.example
  subscriber_name: file_agent
  digital_twin:
    instance_id: ocid1.iotdigitaltwininstance.oc1..device
  content_path: file.commandDetails
  response_endpoint: iot/v1/file/rsp
object_storage:
  namespace_name: namespace
  bucket_name: uploads
commands:
  demo: /opt/demo.sh
""",
        encoding="utf-8",
    )
    return config_path


def test_subscribe_registers_db_aq_subscriber(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path)
    calls = {}
    domain_context = cli_module.IOTDomainContext(
        domain_short_id="abc123",
        db_connection_string="tcps:adb.example.com:1521/service",
        db_token_scope="urn:oracle:db::id::scope",
    )

    monkeypatch.setattr(
        cli_module,
        "create_iot_client",
        lambda config: calls.setdefault("iot_client", object()),
    )
    monkeypatch.setattr(
        cli_module,
        "derive_iot_domain_context",
        lambda iot_client, iot_domain_id: calls.setdefault(
            "derive_args", (iot_client, iot_domain_id)
        )
        and domain_context,
    )

    monkeypatch.setattr(
        cli_module.iot_db,
        "db_connect",
        lambda **kwargs: calls.setdefault("db_connect_kwargs", kwargs) or object(),
    )

    def build_rule(**kwargs):
        calls["rule_kwargs"] = kwargs
        return "rule"

    monkeypatch.setattr(cli_module.iot_db, "build_subscriber_rule", build_rule)
    monkeypatch.setattr(
        cli_module.iot_db,
        "add_subscriber",
        lambda **kwargs: calls.setdefault("add_kwargs", kwargs),
    )
    monkeypatch.setattr(
        cli_module.iot_db,
        "db_disconnect",
        lambda connection: calls.setdefault("disconnected", connection),
    )

    result = CliRunner().invoke(
        cli,
        ["--config-file", str(config_path), "subscribe"],
    )

    assert result.exit_code == 0
    assert calls["derive_args"][1] == "ocid1.iotdomain.oc1.eu-frankfurt-1.example"
    assert calls["db_connect_kwargs"]["db_connect_string"] == (
        "tcps:adb.example.com:1521/service"
    )
    assert calls["db_connect_kwargs"]["db_token_scope"] == "urn:oracle:db::id::scope"
    assert calls["add_kwargs"]["queue_name"] == "ABC123__IOT.NORMALIZED_DATA"
    assert calls["add_kwargs"]["subscriber_name"] == "file_agent"
    assert calls["add_kwargs"]["rule"] == "rule"
    assert "registered" in result.output


def test_janitor_list_outputs_file_agent_pars(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path)
    par = type(
        "PAR",
        (),
        {
            "id": "par-id",
            "name": "file-agent:device:txn-1",
            "object_name": "device/txn-1/",
            "time_created": "2026-04-28T12:00:00Z",
        },
    )()
    service = type("Service", (), {"list_file_agent_pars": lambda self: [par]})()
    monkeypatch.setattr(cli_module, "create_par_service", lambda config: service)

    result = CliRunner().invoke(
        cli,
        ["--config-file", str(config_path), "janitor", "list"],
    )

    assert result.exit_code == 0
    assert "par-id" in result.output
    assert "file-agent:device:txn-1" in result.output


def test_janitor_prune_outputs_deleted_count(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path)
    calls = {}

    class FakeService:
        def prune(self, min_age_minutes):
            calls["min_age_minutes"] = min_age_minutes
            return ["old-id"]

    monkeypatch.setattr(cli_module, "create_par_service", lambda config: FakeService())

    result = CliRunner().invoke(
        cli,
        [
            "--config-file",
            str(config_path),
            "janitor",
            "prune",
            "--min-age-minutes",
            "60",
        ],
    )

    assert result.exit_code == 0
    assert calls["min_age_minutes"] == 60
    assert "Deleted 1 PAR(s)" in result.output
