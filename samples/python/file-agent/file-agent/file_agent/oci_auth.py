#
# OCI authentication helpers.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

"""OCI authentication helpers."""

import logging

from oci import config as oci_config
from oci import signer as oci_signer
from oci.auth import signers as oci_auth_signers

logger = logging.getLogger(__name__)


def get_oci_config(profile: str, auth: str) -> tuple[dict, dict]:
    """Return OCI SDK config and signer kwargs for the configured auth type."""
    match auth:
        case "ConfigFileAuthentication":
            logger.debug("OCI authentication: config file")
            return oci_config.from_file(profile_name=profile), {}
        case "InstancePrincipal":
            logger.debug("OCI authentication: instance principal")
            return {}, {
                "signer": oci_auth_signers.InstancePrincipalsSecurityTokenSigner()
            }
        case "SecurityToken":
            logger.debug("OCI authentication: security token")
            config = oci_config.from_file(profile_name=profile)
            with open(config["security_token_file"]) as token_file:
                token = token_file.read()
            private_key = oci_signer.load_private_key_from_file(config["key_file"])
            return config, {
                "signer": oci_auth_signers.SecurityTokenSigner(token, private_key)
            }
        case _:
            raise ValueError(f"unsupported auth scheme {auth}")
