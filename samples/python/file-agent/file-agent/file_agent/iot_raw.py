#
# OCI IoT raw-command response publishing.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

"""OCI IoT raw-command response publishing."""

import logging
from typing import Any

from oci import exceptions as oci_exceptions
from oci import iot as oci_iot

from .models import ProtocolResponse

logger = logging.getLogger(__name__)


def send_response(
    iot_client: oci_iot.IotClient,
    digital_twin_instance_id: str,
    endpoint: str,
    response: ProtocolResponse,
) -> bool:
    """Send a file-agent protocol response to a Digital Twin instance."""
    return send_payload(
        iot_client=iot_client,
        digital_twin_instance_id=digital_twin_instance_id,
        endpoint=endpoint,
        payload=response.to_payload(),
    )


def send_payload(
    iot_client: oci_iot.IotClient,
    digital_twin_instance_id: str,
    endpoint: str,
    payload: dict[str, Any],
) -> bool:
    """Send an arbitrary JSON response payload to a Digital Twin instance."""
    raw_command = oci_iot.models.InvokeRawJsonCommandDetails(
        request_duration="PT60M",
        request_endpoint=endpoint,
        request_data=payload,
    )
    try:
        result = iot_client.invoke_raw_command(
            digital_twin_instance_id=digital_twin_instance_id,
            invoke_raw_command_details=raw_command,
        )
    except oci_exceptions.ServiceError as exc:
        logger.error(
            "Cannot send response to Digital Twin Instance %s: %s %s",
            digital_twin_instance_id,
            exc.status,
            exc.message,
        )
        return False

    if result and result.status == 202:
        logger.debug(
            "Response sent to Digital Twin Instance %s", digital_twin_instance_id
        )
        return True

    logger.error(
        "Unexpected raw-command response for %s: %s - %s",
        digital_twin_instance_id,
        result.status if result else None,
        result.data if result else None,
    )
    return False
