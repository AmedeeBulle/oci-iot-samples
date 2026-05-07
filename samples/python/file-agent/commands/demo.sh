#!/usr/bin/env bash
#
# Demo command for the file agent.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

# shellcheck disable=SC2016

set -euo pipefail

PGM=${0##*/}
readonly PGM

# Get arguments
if [[ $# -ne 1 ]]; then
  echo "Usage: ${PGM} message_in_json_format" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "${PGM}: jq is required" >&2
  exit 127
fi

message="$1"
if ! jq -e . >/dev/null 2>&1 <<<"${message}"; then
  echo "${PGM}: invalid message JSON" >&2
  exit 1
fi

message_id=$(jq -r .message_id <<<"${message}")
instance_id=$(jq -r .digital_twin_instance_id <<<"${message}")
display_name=$(jq -r .digital_twin_display_name <<<"${message}")
time_observed=$(jq -r .time_observed <<<"${message}")
content_path=$(jq -r .content_path <<<"${message}")
request=$(jq .request <<<"${message}")

echo "${PGM}: === Message metadata ==="
echo "${PGM}: Message ID   : ${message_id}"
echo "${PGM}: Instance ID  : ${instance_id}"
echo "${PGM}: Display name : ${display_name}"
echo "${PGM}: Time observed: ${time_observed}"
echo "${PGM}: Content path : ${content_path}"

request_id=$(jq -r .id <<<"${request}")
data=$(jq .data <<<"${request}")
echo
echo "${PGM}: === Message request ==="
echo "${PGM}: Request Id: ${request_id}"
echo "${PGM}: Data:"
jq <<<"${data}"

if jq -e 'if (.parameters | type) == "object" then (.parameters | has("sleep")) else false end' <<<"${data}" >/dev/null; then
  sleep=$(jq -er '.parameters.sleep | select(type == "number" and . >= 0)' <<<"${data}") || {
    echo "${PGM}: parameters.sleep must be a non-negative number" >&2
    exit 1
  }
  echo "${PGM}: sleeping for ${sleep} seconds"
  sleep "${sleep}"
fi

echo "${PGM}: Done"
