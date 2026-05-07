#
# Protocol models for file upload transactions.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

"""Protocol models for file upload transactions."""

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator

Operation = Literal["prepare-upload", "complete-upload"]
TRANSACTION_ID_MAX_LENGTH = 128
TRANSACTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_transaction_id(value: str) -> str:
    """Validate a transaction id before it is used in paths or URLs."""
    if (
        not isinstance(value, str)
        or len(value) < 1
        or len(value) > TRANSACTION_ID_MAX_LENGTH
        or not TRANSACTION_ID_PATTERN.fullmatch(value)
    ):
        raise ValueError(
            "Transaction id must be 1-128 characters of A-Z, a-z, 0-9, '.', "
            "'_', or '-', and must start with a letter or digit"
        )
    return value


class PARRequestData(BaseModel):
    """Data payload for a PAR staging request."""

    model_config = ConfigDict(extra="forbid")

    ttl: PositiveInt = 60


class UploadRequestData(BaseModel):
    """Data payload for an upload completion request."""

    model_config = ConfigDict(extra="forbid")

    command: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProtocolRequest(BaseModel):
    """Device request payload after adapter mapping."""

    model_config = ConfigDict(extra="forbid")

    op: Operation
    id: str = Field(min_length=1, max_length=TRANSACTION_ID_MAX_LENGTH)
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def check_transaction_id(cls, value: str) -> str:
        """Reject ids that are unsafe as Object Storage path components."""
        return validate_transaction_id(value)


class ProtocolResponse(BaseModel):
    """Backend response payload sent to the device."""

    model_config = ConfigDict(extra="forbid")

    op: Operation
    id: str
    data: dict[str, Any] = Field(default_factory=dict)
    code: int
    message: str

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-serializable response payload."""
        return self.model_dump(mode="json")


class InboundMessage(BaseModel):
    """Normalized queue message carrying a file-agent request."""

    model_config = ConfigDict(
        extra="ignore",
        validate_by_alias=True,
        validate_by_name=False,
    )

    message_id: str = ""
    digital_twin_instance_id: str = Field(validation_alias="digitalTwinInstanceId")
    digital_twin_display_name: str = "unknown"
    time_observed: str = Field(validation_alias="timeObserved")
    content_path: str = Field(validation_alias="contentPath")
    request: ProtocolRequest = Field(validation_alias="value")
