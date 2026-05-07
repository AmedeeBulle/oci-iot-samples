#
# Object Storage pre-authenticated request lifecycle helpers.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

"""Object Storage pre-authenticated request lifecycle helpers."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from oci import object_storage
from oci.object_storage.models import CreatePreauthenticatedRequestDetails

from .models import validate_transaction_id


@dataclass(frozen=True)
class StageUploadResult:
    """Result returned after creating an upload PAR."""

    par_id: str
    upload_url: str
    object_prefix: str
    time_expires: datetime


class PARService:
    """Manage file-agent Object Storage PARs."""

    def __init__(
        self,
        object_storage_client: object_storage.ObjectStorageClient,
        bucket_name: str,
        namespace_name: Optional[str] = None,
        max_ttl_minutes: int = 60,
        par_name_prefix: str = "file-agent",
        now: Callable[[], datetime] | None = None,
    ):
        """Initialize the PAR service."""
        self.object_storage_client = object_storage_client
        self.namespace_name = namespace_name
        self.bucket_name = bucket_name
        self.max_ttl_minutes = max_ttl_minutes
        self.par_name_prefix = par_name_prefix
        self._now = now or (lambda: datetime.now(timezone.utc))

    def stage_upload(
        self,
        digital_twin_instance_id: str,
        transaction_id: str,
        requested_ttl_minutes: int,
    ) -> StageUploadResult:
        """Create a write-only PAR for one device transaction prefix."""
        ttl_minutes = max(1, min(requested_ttl_minutes, self.max_ttl_minutes))
        time_expires = self._utc_now() + timedelta(minutes=ttl_minutes)
        object_prefix = self.object_prefix(digital_twin_instance_id, transaction_id)
        details = CreatePreauthenticatedRequestDetails(
            name=self.par_name(digital_twin_instance_id, transaction_id),
            object_name=object_prefix,
            access_type=CreatePreauthenticatedRequestDetails.ACCESS_TYPE_ANY_OBJECT_WRITE,
            time_expires=time_expires,
        )

        response = self.object_storage_client.create_preauthenticated_request(
            self._namespace_name(),
            self.bucket_name,
            details,
        )

        return StageUploadResult(
            par_id=response.data.id,
            upload_url=self._upload_url(response.data.access_uri, object_prefix),
            object_prefix=object_prefix,
            time_expires=time_expires,
        )

    def complete_upload(
        self, digital_twin_instance_id: str, transaction_id: str
    ) -> bool:
        """Delete the PAR associated with a completed upload transaction."""
        par = self.find_upload_par(digital_twin_instance_id, transaction_id)
        if par is None:
            return False

        self.object_storage_client.delete_preauthenticated_request(
            self._namespace_name(),
            self.bucket_name,
            par.id,
        )
        return True

    def find_upload_par(self, digital_twin_instance_id: str, transaction_id: str):
        """Return the matching file-agent PAR summary, if it exists."""
        name = self.par_name(digital_twin_instance_id, transaction_id)
        for par in self.list_file_agent_pars():
            if par.name == name:
                return par
        return None

    def list_file_agent_pars(self):
        """List Object Storage PARs created by file-agent."""
        page = None
        pars = []
        while True:
            kwargs = {}
            if page is not None:
                kwargs["page"] = page
            response = self.object_storage_client.list_preauthenticated_requests(
                self._namespace_name(),
                self.bucket_name,
                **kwargs,
            )
            pars.extend(
                par
                for par in response.data
                if getattr(par, "name", "").startswith(f"{self.par_name_prefix}:")
            )
            page = getattr(response, "next_page", None)
            if not page:
                return pars

    def prune(self, min_age_minutes: int = 0) -> list[str]:
        """Delete file-agent PARs older than the given age threshold."""
        cutoff = self._utc_now() - timedelta(minutes=min_age_minutes)
        pruned = []
        for par in self.list_file_agent_pars():
            time_created = self._as_utc(getattr(par, "time_created", None))
            if time_created is None or time_created > cutoff:
                continue
            self.object_storage_client.delete_preauthenticated_request(
                self._namespace_name(),
                self.bucket_name,
                par.id,
            )
            pruned.append(par.id)
        return pruned

    def par_name(self, digital_twin_instance_id: str, transaction_id: str) -> str:
        """Return the deterministic PAR name for a device transaction."""
        transaction_id = validate_transaction_id(transaction_id)
        return f"{self.par_name_prefix}:{digital_twin_instance_id}:{transaction_id}"

    @staticmethod
    def object_prefix(digital_twin_instance_id: str, transaction_id: str) -> str:
        """Return the Object Storage prefix assigned to a device transaction."""
        transaction_id = validate_transaction_id(transaction_id)
        return f"{digital_twin_instance_id}/{transaction_id}/"

    def _namespace_name(self) -> str:
        if self.namespace_name:
            return self.namespace_name
        response = self.object_storage_client.get_namespace()
        self.namespace_name = response.data
        return self.namespace_name

    def _full_access_url(self, access_uri: str) -> str:
        if access_uri.startswith(("http://", "https://")):
            return access_uri
        endpoint = self.object_storage_client.base_client.endpoint.rstrip("/")
        return f"{endpoint}{access_uri}"

    def _upload_url(self, access_uri: str, object_prefix: str) -> str:
        access_url = self._full_access_url(access_uri)
        normalized_prefix = object_prefix.strip("/")
        if access_url.rstrip("/").endswith(normalized_prefix):
            return f"{access_url.rstrip('/')}/"
        return f"{access_url.rstrip('/')}/{normalized_prefix}/"

    def _utc_now(self) -> datetime:
        return self._as_utc(self._now()) or datetime.now(timezone.utc)

    @staticmethod
    def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
