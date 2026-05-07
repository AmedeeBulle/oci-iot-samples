/*
 * mqtt_manager.h
 *
 * Handle MQTT messaging
 *
 * Copyright (c) 2026 Oracle and/or its affiliates.
 * Licensed under the Universal Permissive License v 1.0 as shown at
 * https://oss.oracle.com/licenses/upl/
 *
 * SPDX-License-Identifier: UPL-1.0
 */

#pragma once

#include "freertos/FreeRTOS.h"

#include "freertos/queue.h"

#include "config_manager.h"
#include "esp_err.h"

#define MQTT_MANAGER_MAX_COMMAND_TOPIC_LEN (CONFIG_MGR_MAX_TOPIC_LEN + 64)
#define MQTT_MANAGER_MAX_COMMAND_PAYLOAD_LEN 384

typedef struct {
    char topic[MQTT_MANAGER_MAX_COMMAND_TOPIC_LEN];
    char payload[MQTT_MANAGER_MAX_COMMAND_PAYLOAD_LEN];
} mqtt_msg_t;

/**
 * Initialize and start the MQTT client.
 */
esp_err_t start_mqtt_client(mqtt_config_t *mqtt_config, iot_certs_t *iot_certs, QueueHandle_t event_data_queue);

/**
 * Publish telemetry payload.
 */
esp_err_t publish_telemetry(const char *payload);

/**
 * Publish a response message.
 */
esp_err_t publish_response(const char *command_topic, const char *command_name, const char *status);
