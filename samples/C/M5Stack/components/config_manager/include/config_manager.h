/*
 * config_manager.h
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

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#define CONFIG_MGR_MAX_SSID_LEN 32
#define CONFIG_MGR_MAX_PASSWORD_LEN 64
#define CONFIG_MGR_MAX_TOPIC_LEN 128
#define CONFIG_MGR_MAX_HOST_LEN 128
#define CONFIG_MGR_MAX_FILE_PATH 32
#define CONFIG_MGR_MAX_CERT_NAME 64

typedef struct {
    char i2c_port;  // 'A' or 'B'
    uint8_t display_brightness;
    uint16_t display_timeout;
} hardware_config_t;

typedef struct {
    char ssid[CONFIG_MGR_MAX_SSID_LEN];
    char password[CONFIG_MGR_MAX_PASSWORD_LEN];
} wireless_config_t;

typedef struct {
    uint16_t port;
    uint16_t keep_alive;
    uint16_t publish_freq;
    uint8_t qos;
    char host[CONFIG_MGR_MAX_HOST_LEN];
    char ca_cert[CONFIG_MGR_MAX_FILE_PATH];
    char user[CONFIG_MGR_MAX_SSID_LEN];
    char password[CONFIG_MGR_MAX_PASSWORD_LEN];
    char client_cert[CONFIG_MGR_MAX_FILE_PATH];
    char client_key[CONFIG_MGR_MAX_FILE_PATH];
    char topic[CONFIG_MGR_MAX_TOPIC_LEN];
} mqtt_config_t;

typedef struct {
    char ca_cert[CONFIG_MGR_MAX_FILE_PATH];
} ota_config_t;

typedef struct {
    uint32_t version;
    hardware_config_t hardware;
    wireless_config_t wifi;
    ota_config_t ota;
    mqtt_config_t mqtt;
} iot_config_t;

/*
 * Certificates
 */
typedef struct {
    char *client_cert;
    char *client_key;
    char *mqtt_ca_cert;
    char *ota_ca_cert;
} iot_certs_t;

/**
 * Initialize configuration and certificates.
 */
esp_err_t config_manager_init(iot_config_t *iot_config, iot_certs_t *iot_certs);
