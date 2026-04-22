/*
 * update_manager.c
 *
 * Hardware and main configuration parameters
 *
 * Copyright (c) 2026 Oracle and/or its affiliates.
 * Licensed under the Universal Permissive License v 1.0 as shown at
 * https://oss.oracle.com/licenses/upl/
 *
 * SPDX-License-Identifier: UPL-1.0
 */

#include "update_manager.h"

#include <stdio.h>
#include <sys/stat.h>

#include "bsp/m5stack_core_s3.h"
#include "esp_https_ota.h"
#include "esp_ota_ops.h"

#define FIRMWARE_FILENAME "oci-iot.bin"

static const char *TAG = "update_manager";

/**
 * Apply firmware update from SD card if present.
 *
 * If an update is found, flash it in the OTA available partition
 * Return ESP_OK if a new firmware is installed (reboot required)
 * Assume that the SD card is already mounted on BSP_SD_MOUNT_POINT
 */
esp_err_t check_for_sd_update(void)
{
    struct stat st;
    if (stat(BSP_SD_MOUNT_POINT "/" FIRMWARE_FILENAME, &st) != 0) {
        return ESP_ERR_NOT_FOUND;
    }
    FILE *f = fopen(BSP_SD_MOUNT_POINT "/" FIRMWARE_FILENAME, "rb");
    if (!f) {
        return ESP_FAIL;
    }
    const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
    if (!update_partition) {
        fclose(f);
        return ESP_FAIL;
    }
    esp_ota_handle_t ota_handle = 0;
    esp_err_t ret = esp_ota_begin(update_partition, OTA_SIZE_UNKNOWN, &ota_handle);
    if (ret != ESP_OK) {
        fclose(f);
        return ret;
    }
    uint8_t *buffer = malloc(4096);
    if (!buffer) {
        esp_ota_end(ota_handle);
        fclose(f);
        return ESP_ERR_NO_MEM;
    }
    size_t read_bytes;
    while ((read_bytes = fread(buffer, 1, 4096, f)) > 0) {
        ret = esp_ota_write(ota_handle, buffer, read_bytes);
        if (ret != ESP_OK) {
            break;
        }
    }
    free(buffer);
    fclose(f);
    if (ret == ESP_OK) {
        ret = esp_ota_end(ota_handle);
    } else {
        esp_ota_end(ota_handle);
    }
    if (ret == ESP_OK) {
        ret = esp_ota_set_boot_partition(update_partition);
    }
    if (ret == ESP_OK) {
        remove(BSP_SD_MOUNT_POINT "/" FIRMWARE_FILENAME);
        ESP_LOGI(TAG, "Update from SD card applied - Device will reboot");
    }
    return ret;
}

/**
 * Start HTTPS OTA update from URL.
 *
 * A CA certificate must be provided for OTA. For development purpose, if an
 * insecure connection is required, "CONFIG_ESP_HTTPS_OTA_ALLOW_HTTP=y" can
 * be set in your sdkconfig -- See
 * https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/kconfig-reference.html#config-esp-https-ota-allow-http
 *
 * Return ESP_OK if a new firmware is installed (reboot required)
 */
esp_err_t start_https_ota(const char *url, const char *ca_cert)
{
    if (!url || url[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }
    esp_http_client_config_t http_config = {
        .url = url,
        .cert_pem = ca_cert,
        .skip_cert_common_name_check = (ca_cert == NULL),
        .timeout_ms = 10000,
    };
    esp_https_ota_config_t ota_config = {
        .http_config = &http_config,
    };
    ESP_LOGI(TAG, "Downloading OTA update");
    esp_err_t ret = esp_https_ota(&ota_config);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "OTA Downloaded and applied");
    } else {
        ESP_LOGE(TAG, "OTA update failed: %s", esp_err_to_name(ret));
    }
    return ret;
}
