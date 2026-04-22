/*
 * update_manager.h
 *
 * Hardware and main configuration parameters
 *
 * Copyright (c) 2026 Oracle and/or its affiliates.
 * Licensed under the Universal Permissive License v 1.0 as shown at
 * https://oss.oracle.com/licenses/upl/
 *
 * SPDX-License-Identifier: UPL-1.0
 */

#pragma once

#include "esp_err.h"

/**
 * Apply firmware update from SD card if present.
 */
esp_err_t check_for_sd_update(void);

/**
 * Start HTTPS OTA update from URL.
 */
esp_err_t start_https_ota(const char *url, const char *ca_cert);
