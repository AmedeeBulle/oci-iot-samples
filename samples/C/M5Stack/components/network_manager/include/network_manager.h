/*
 * network_manager.h
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
 * Connect to a Wi-Fi network.
 */
esp_err_t wifi_connect(const char *ssid, const char *password);

/**
 * Wait until SNTP sync completes.
 */
esp_err_t wait_for_time_sync();
