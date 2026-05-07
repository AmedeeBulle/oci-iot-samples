#
# Tests for Object Storage PAR lifecycle helpers.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

from datetime import datetime, timedelta, timezone

from oci.object_storage.models import CreatePreauthenticatedRequestDetails

from file_agent.object_storage import PARService


class _FakeObjectStorageClient:
    def __init__(self):
        self.base_client = type(
            "BaseClient",
            (),
            {"endpoint": "https://objectstorage.eu-frankfurt-1.oraclecloud.com"},
        )()
        self.created = []
        self.deleted = []
        self.summaries = []
        self.summary_pages = None
        self.list_calls = []

    def create_preauthenticated_request(
        self, namespace_name, bucket_name, create_preauthenticated_request_details
    ):
        self.created.append(
            (namespace_name, bucket_name, create_preauthenticated_request_details)
        )
        return type(
            "Response",
            (),
            {
                "data": type(
                    "PAR",
                    (),
                    {
                        "id": "par-id",
                        "access_uri": "/p/token/n/namespace/b/uploads/o/",
                    },
                )()
            },
        )()

    def list_preauthenticated_requests(self, namespace_name, bucket_name, **kwargs):
        self.list_calls.append((namespace_name, bucket_name, kwargs))
        if self.summary_pages is None:
            return type("Response", (), {"data": self.summaries})()

        page = kwargs.get("page")
        page_index = 0 if page is None else int(page)
        next_page = (
            str(page_index + 1) if page_index + 1 < len(self.summary_pages) else None
        )
        return type(
            "Response",
            (),
            {"data": self.summary_pages[page_index], "next_page": next_page},
        )()

    def delete_preauthenticated_request(self, namespace_name, bucket_name, par_id):
        self.deleted.append((namespace_name, bucket_name, par_id))


def _summary(name, par_id="par-id", created=None):
    return type(
        "Summary",
        (),
        {
            "id": par_id,
            "name": name,
            "time_created": created
            or datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc),
        },
    )()


def test_stage_upload_caps_ttl_and_creates_write_only_prefix_par():
    now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    client = _FakeObjectStorageClient()
    service = PARService(
        object_storage_client=client,
        namespace_name="namespace",
        bucket_name="uploads",
        max_ttl_minutes=30,
        now=lambda: now,
    )

    result = service.stage_upload(
        digital_twin_instance_id="ocid1.iotdigitaltwininstance.oc1..device",
        transaction_id="txn-1",
        requested_ttl_minutes=120,
    )

    assert result.par_id == "par-id"
    assert result.upload_url == (
        "https://objectstorage.eu-frankfurt-1.oraclecloud.com"
        "/p/token/n/namespace/b/uploads/o/"
        "ocid1.iotdigitaltwininstance.oc1..device/txn-1/"
    )
    assert result.object_prefix == "ocid1.iotdigitaltwininstance.oc1..device/txn-1/"

    [(namespace_name, bucket_name, details)] = client.created
    assert namespace_name == "namespace"
    assert bucket_name == "uploads"
    assert isinstance(details, CreatePreauthenticatedRequestDetails)
    assert details.name == "file-agent:ocid1.iotdigitaltwininstance.oc1..device:txn-1"
    assert details.object_name == "ocid1.iotdigitaltwininstance.oc1..device/txn-1/"
    assert details.access_type == "AnyObjectWrite"
    assert details.time_expires == now + timedelta(minutes=30)


def test_complete_upload_deletes_matching_file_agent_par():
    client = _FakeObjectStorageClient()
    client.summaries = [
        _summary("unrelated", "other-id"),
        _summary("file-agent:ocid1.iotdigitaltwininstance.oc1..device:txn-1", "par-id"),
    ]
    service = PARService(
        object_storage_client=client,
        namespace_name="namespace",
        bucket_name="uploads",
    )

    deleted = service.complete_upload(
        digital_twin_instance_id="ocid1.iotdigitaltwininstance.oc1..device",
        transaction_id="txn-1",
    )

    assert deleted is True
    assert client.deleted == [("namespace", "uploads", "par-id")]


def test_complete_upload_checks_all_par_list_pages():
    client = _FakeObjectStorageClient()
    client.summary_pages = [
        [_summary("file-agent:device:txn-0", "first-page-id")],
        [
            _summary(
                "file-agent:ocid1.iotdigitaltwininstance.oc1..device:txn-1", "par-id"
            )
        ],
    ]
    service = PARService(
        object_storage_client=client,
        namespace_name="namespace",
        bucket_name="uploads",
    )

    deleted = service.complete_upload(
        digital_twin_instance_id="ocid1.iotdigitaltwininstance.oc1..device",
        transaction_id="txn-1",
    )

    assert deleted is True
    assert client.deleted == [("namespace", "uploads", "par-id")]
    assert [call[2].get("page") for call in client.list_calls] == [None, "1"]


def test_prune_deletes_only_file_agent_pars_older_than_threshold():
    now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    client = _FakeObjectStorageClient()
    client.summaries = [
        _summary("file-agent:device:old", "old-id", now - timedelta(hours=3)),
        _summary("file-agent:device:new", "new-id", now - timedelta(minutes=10)),
        _summary("manual:device:old", "manual-id", now - timedelta(hours=3)),
    ]
    service = PARService(
        object_storage_client=client,
        namespace_name="namespace",
        bucket_name="uploads",
        now=lambda: now,
    )

    pruned = service.prune(min_age_minutes=60)

    assert pruned == ["old-id"]
    assert client.deleted == [("namespace", "uploads", "old-id")]


def test_prune_checks_all_par_list_pages():
    now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    client = _FakeObjectStorageClient()
    client.summary_pages = [
        [_summary("file-agent:device:first", "first-id", now - timedelta(hours=3))],
        [_summary("file-agent:device:second", "second-id", now - timedelta(hours=3))],
    ]
    service = PARService(
        object_storage_client=client,
        namespace_name="namespace",
        bucket_name="uploads",
        now=lambda: now,
    )

    pruned = service.prune(min_age_minutes=60)

    assert pruned == ["first-id", "second-id"]
    assert client.deleted == [
        ("namespace", "uploads", "first-id"),
        ("namespace", "uploads", "second-id"),
    ]
    assert [call[2].get("page") for call in client.list_calls] == [None, "1"]
