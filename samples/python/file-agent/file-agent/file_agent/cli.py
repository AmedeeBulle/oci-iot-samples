#
# Command-line interface for the file agent.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

"""Command-line interface for the file agent."""

import logging
import os
import queue
import threading
from typing import Optional, TextIO

import click
from oci import iot as oci_iot
from oci import object_storage as oci_object_storage

from . import __version__, iot_db, iot_raw, oci_auth
from . import config as app_config
from .iot_context import IOTDomainContext, derive_iot_domain_context
from .object_storage import PARService
from .processor import STOP_WORKER, MessageProcessor, command_worker

LOGGER_FMT = (
    "{asctime} - {levelname:8} - {filename:12.12} - {threadName:12.12} - {message}"
)


class CLIContext:
    """Click context object."""

    def __init__(self):
        """Initialize the context object."""
        self.config: Optional[app_config.AppConfig] = None
        self.connection = None


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable info logging.")
@click.option("-d", "--debug", is_flag=True, help="Enable debug logging.")
@click.option(
    "--config-file",
    type=click.File(mode="r"),
    default=app_config.DEFAULT_CONFIG_FILE,
    help="Path to the file-agent YAML configuration.",
    show_default=True,
)
@click.version_option(version=__version__)
@click.pass_context
def cli(
    ctx: click.Context,
    verbose: bool,
    debug: bool,
    config_file: TextIO,
) -> None:
    """Manage OCI IoT file upload transactions."""
    ctx.ensure_object(CLIContext)
    logging.basicConfig(level=_log_level(verbose, debug), format=LOGGER_FMT, style="{")
    if debug:
        _quiet_oci_loggers()
    try:
        ctx.obj.config = app_config.load_config(config_file)
    except Exception as exc:
        raise click.UsageError(f"Invalid configuration: {exc}") from exc


@cli.command()
@click.pass_context
def subscribe(ctx: click.Context) -> None:
    """Register the normalized-data queue subscriber."""
    config = _require_config(ctx)
    iot_client = create_iot_client(config)
    domain_context = derive_iot_domain_context(iot_client, config.iot.domain_id)
    connection = _connect_database(config, domain_context)
    try:
        rule = iot_db.build_subscriber_rule(
            connection=connection,
            iot_domain_short_id=domain_context.domain_short_id,
            digital_twin_instance_id=config.iot.digital_twin.instance_id,
            display_name=config.iot.digital_twin.display_name,
            content_path=config.iot.content_path,
        )
        iot_db.add_subscriber(
            connection=connection,
            queue_name=queue_name(domain_context),
            subscriber_name=config.iot.subscriber_name,
            rule=rule,
        )
    finally:
        iot_db.db_disconnect(connection)

    click.echo(f"Subscriber {config.iot.subscriber_name} registered")


@cli.command()
@click.pass_context
def unsubscribe(ctx: click.Context) -> None:
    """Remove the normalized-data queue subscriber."""
    config = _require_config(ctx)
    iot_client = create_iot_client(config)
    domain_context = derive_iot_domain_context(iot_client, config.iot.domain_id)
    connection = _connect_database(config, domain_context)
    try:
        iot_db.remove_subscriber(
            connection=connection,
            queue_name=queue_name(domain_context),
            subscriber_name=config.iot.subscriber_name,
        )
    finally:
        iot_db.db_disconnect(connection)

    click.echo(f"Subscriber {config.iot.subscriber_name} removed")


@cli.command()
@click.pass_context
def monitor(ctx: click.Context) -> None:
    """Monitor file upload requests."""
    config = _require_config(ctx)
    iot_client, object_storage_client = create_oci_clients(config)
    domain_context = derive_iot_domain_context(iot_client, config.iot.domain_id)
    par_service = create_par_service(config, object_storage_client)
    connection = _connect_database(config, domain_context)
    work_queue: queue.Queue = queue.Queue()

    def responder(message, response):
        iot_raw.send_response(
            iot_client=iot_client,
            digital_twin_instance_id=message.digital_twin_instance_id,
            endpoint=config.iot.response_endpoint,
            response=response,
        )

    def invalid_message_handler(digital_twin_instance_id, _error):
        iot_raw.send_payload(
            iot_client=iot_client,
            digital_twin_instance_id=digital_twin_instance_id,
            endpoint=config.iot.response_endpoint,
            payload={"code": 400, "message": "Bad request"},
        )

    processor = MessageProcessor(
        par_service=par_service,
        commands=config.commands,
        responder=responder,
    )
    worker = threading.Thread(
        target=command_worker,
        name="CmdWorker",
        kwargs={"work_queue": work_queue, "processor": processor},
    )
    worker.start()

    class ProcessingQueue:
        def put(self, message):
            processor.handle_message(message, command_queue=work_queue)

    try:
        iot_db.dequeue_messages(
            connection=connection,
            queue_name=queue_name(domain_context),
            subscriber_name=config.iot.subscriber_name,
            iot_domain_short_id=domain_context.domain_short_id,
            message_queue=ProcessingQueue(),
            invalid_message_handler=invalid_message_handler,
        )
    except KeyboardInterrupt:
        click.echo("\nInterrupted")
    finally:
        work_queue.put(STOP_WORKER)
        work_queue.join()
        worker.join()
        iot_db.db_disconnect(connection)


@cli.group()
def janitor() -> None:
    """Inspect and prune stale upload PARs."""


@janitor.command(name="list")
@click.pass_context
def janitor_list(ctx: click.Context) -> None:
    """List active file-agent PARs."""
    service = create_par_service(_require_config(ctx))
    for par in service.list_file_agent_pars():
        click.echo(
            "\t".join(
                [
                    getattr(par, "id", ""),
                    getattr(par, "name", ""),
                    getattr(par, "object_name", ""),
                    str(getattr(par, "time_created", "")),
                ]
            )
        )


@janitor.command(name="prune")
@click.option(
    "--min-age-minutes",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Only prune PARs at least this many minutes old.",
)
@click.pass_context
def janitor_prune(ctx: click.Context, min_age_minutes: int) -> None:
    """Delete stale file-agent PARs."""
    service = create_par_service(_require_config(ctx))
    deleted = service.prune(min_age_minutes=min_age_minutes)
    click.echo(f"Deleted {len(deleted)} PAR(s)")


def queue_name(domain_context: IOTDomainContext) -> str:
    """Return the normalized-data queue name for the IoT domain."""
    return f"{domain_context.domain_short_id}__iot.normalized_data".upper()


def create_oci_clients(
    config: app_config.AppConfig,
) -> tuple[oci_iot.IotClient, oci_object_storage.ObjectStorageClient]:
    """Create OCI IoT and Object Storage clients."""
    return create_iot_client(config), create_object_storage_client(config)


def create_iot_client(config: app_config.AppConfig) -> oci_iot.IotClient:
    """Create an OCI IoT client."""
    oci_config, signer = _oci_config_and_signer(config)
    return oci_iot.IotClient(config=oci_config, **signer)


def create_object_storage_client(
    config: app_config.AppConfig,
) -> oci_object_storage.ObjectStorageClient:
    """Create an OCI Object Storage client."""
    oci_config, signer = _oci_config_and_signer(config)
    return oci_object_storage.ObjectStorageClient(config=oci_config, **signer)


def _oci_config_and_signer(config: app_config.AppConfig) -> tuple[dict, dict]:
    """Return OCI config and signer kwargs for configured auth."""
    profile = config.oci.profile or os.getenv("OCI_CLI_PROFILE", "DEFAULT")
    return oci_auth.get_oci_config(profile, config.oci.auth_type)


def create_par_service(
    config: app_config.AppConfig,
    object_storage_client: Optional[oci_object_storage.ObjectStorageClient] = None,
) -> PARService:
    """Create a PAR service from app configuration."""
    if object_storage_client is None:
        object_storage_client = create_object_storage_client(config)
    return PARService(
        object_storage_client=object_storage_client,
        namespace_name=config.object_storage.namespace_name,
        bucket_name=config.object_storage.bucket_name,
        max_ttl_minutes=config.object_storage.max_ttl_minutes,
        par_name_prefix=config.object_storage.par_name_prefix,
    )


def _connect_database(
    config: app_config.AppConfig,
    domain_context: IOTDomainContext,
):
    return iot_db.db_connect(
        db_connect_string=domain_context.db_connection_string,
        db_token_scope=domain_context.db_token_scope,
        thick_mode=config.oracledb.thick_mode,
        lib_dir=config.oracledb.thick_mode_lib_dir,
        oci_auth_type=config.oci.auth_type,
        oci_profile=config.oci.profile,
    )


def _require_config(ctx: click.Context) -> app_config.AppConfig:
    config = ctx.obj.config
    if config is None:
        raise click.ClickException("Configuration was not loaded")
    return config


def _log_level(verbose: bool, debug: bool) -> int:
    if debug:
        return logging.DEBUG
    if verbose:
        return logging.INFO
    return logging.WARNING


def _quiet_oci_loggers() -> None:
    for logger_name in [
        "oci._vendor.urllib3.connectionpool",
        "oci.circuit_breaker",
        "oci.config",
        "oci.util",
    ]:
        logging.getLogger(logger_name).setLevel(logging.INFO)
