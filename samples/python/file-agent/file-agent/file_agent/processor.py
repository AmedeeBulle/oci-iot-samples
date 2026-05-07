#
# Protocol processing and command execution.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

"""Protocol processing and command execution."""

import logging
import queue
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional, TextIO

from pydantic import ValidationError

from .models import (
    InboundMessage,
    PARRequestData,
    ProtocolResponse,
    UploadRequestData,
)

logger = logging.getLogger(__name__)

ResponseSender = Callable[[InboundMessage, ProtocolResponse], None]
CommandRunner = Callable[[list[str]], Any]
STOP_WORKER = object()


@dataclass(frozen=True)
class CommandWorkItem:
    """Queued command execution request."""

    message: InboundMessage
    upload_data: UploadRequestData


class MessageProcessor:
    """Handle file-agent protocol requests."""

    def __init__(
        self,
        par_service,
        commands: dict[str, str],
        responder: ResponseSender,
        command_runner: Optional[CommandRunner] = None,
    ):
        """Initialize a message processor."""
        self.par_service = par_service
        self.commands = commands
        self.responder = responder
        self.command_runner = command_runner or self._default_command_runner

    def handle_message(
        self,
        message: InboundMessage,
        command_queue: Optional[queue.Queue] = None,
    ) -> None:
        """Process an inbound protocol message."""
        match message.request.op:
            case "prepare-upload":
                self._handle_prepare_upload(message)
            case "complete-upload":
                self._handle_complete_upload(message, command_queue)

    def run_command(
        self,
        message: InboundMessage,
        upload_data: UploadRequestData,
    ) -> None:
        """Execute a configured command and send start/completion responses."""
        command_name = upload_data.command
        if not command_name or command_name not in self.commands:
            self._send(message, 422, "Invalid command")
            return

        self._send(message, 201, "Process started")
        try:
            result = self.command_runner(
                [
                    self.commands[command_name],
                    message.model_dump_json(by_alias=True),
                ]
            )
        except Exception:
            logger.exception("Command failed to start: %s", command_name)
            self._send(message, 500, "Process failed")
            return

        if getattr(result, "returncode", 1) == 0:
            self._send(message, 200, "Process completed")
        else:
            self._send(message, 500, "Process failed")

    def _handle_prepare_upload(self, message: InboundMessage) -> None:
        try:
            data = PARRequestData.model_validate(message.request.data)
        except ValidationError:
            logger.exception("Invalid prepare-upload payload")
            self._send(message, 400, "Bad request")
            return

        try:
            result = self.par_service.stage_upload(
                digital_twin_instance_id=message.digital_twin_instance_id,
                transaction_id=message.request.id,
                requested_ttl_minutes=data.ttl,
            )
        except Exception:
            logger.exception("Upload preparation failed")
            self._send(message, 500, "Upload preparation failed")
            return

        self._send(message, 200, "Upload prepared", {"upload_url": result.upload_url})

    def _handle_complete_upload(
        self,
        message: InboundMessage,
        command_queue: Optional[queue.Queue],
    ) -> None:
        try:
            data = UploadRequestData.model_validate(message.request.data)
        except ValidationError:
            logger.exception("Invalid complete-upload payload")
            self._send(message, 400, "Bad request")
            return

        try:
            par_deleted = self.par_service.complete_upload(
                digital_twin_instance_id=message.digital_twin_instance_id,
                transaction_id=message.request.id,
            )
        except Exception:
            logger.exception("PAR deletion failed")
            self._send(message, 500, "PAR deletion failed")
            return

        if not par_deleted:
            self._send(message, 422, "No prepared upload")
            return

        if not data.command:
            self._send(message, 200, "Process completed")
            return

        if data.command not in self.commands:
            self._send(message, 422, "Invalid command")
            return

        self._send(message, 202, "Process queued")
        work_item = CommandWorkItem(message=message, upload_data=data)
        if command_queue is None:
            self.run_command(work_item.message, work_item.upload_data)
        else:
            command_queue.put(work_item)

    def _send(
        self,
        message: InboundMessage,
        code: int,
        response_message: str,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        response = ProtocolResponse(
            op=message.request.op,
            id=message.request.id,
            data=data or {},
            code=code,
            message=response_message,
        )
        self.responder(message, response)

    @staticmethod
    def _default_command_runner(args: list[str]):
        process = subprocess.Popen(
            args,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        stdout_thread = threading.Thread(
            name="stdout",
            target=MessageProcessor._log_stream_lines,
            args=(process.stdout, logger.info),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            name="stderr",
            target=MessageProcessor._log_stream_lines,
            args=(process.stderr, logger.error),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()
        returncode = process.wait()
        stdout_thread.join()
        stderr_thread.join()

        return subprocess.CompletedProcess(args=args, returncode=returncode)

    @staticmethod
    def _log_stream_lines(
        stream: Optional[TextIO],
        log_line: Callable[[str], None],
    ) -> None:
        if stream is None:
            return

        with stream:
            for line in stream:
                log_line(line.rstrip("\r\n"))


def command_worker(work_queue: queue.Queue, processor: MessageProcessor) -> None:
    """Run queued command work items until a stop sentinel is received."""
    while True:
        item = work_queue.get()
        try:
            if item is STOP_WORKER:
                return
            processor.run_command(item.message, item.upload_data)
        finally:
            work_queue.task_done()
