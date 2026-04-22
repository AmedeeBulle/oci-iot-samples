/*
 * sensor_manager.h
 *
 * Sensor abstraction for the ENV III unit (SHT30 + QMP6988)
 *
 * Copyright (c) 2026 Oracle and/or its affiliates.
 * Licensed under the Universal Permissive License v 1.0 as shown at
 * https://oss.oracle.com/licenses/upl/
 *
 * SPDX-License-Identifier: UPL-1.0
 */

#pragma once

#include "esp_err.h"

typedef struct {
    float sht_temperature_c;
    float humidity_percent;
    float qmp_temperature_c;
    float pressure_hpa;
} sensor_data_t;

/**
 * Initialize the ENV III sensors.
 */
esp_err_t env_sensors_init(char port_sel);

/**
 * Read sensor data from the ENV III sensors.
 */
esp_err_t env_sensors_read(sensor_data_t *out_data);
