/*
 * main.c
 *
 * Sample code for the M5Stack CoreS3 to send sensor data over MQTT to the
 * Oracle OCI IoT Platform
 *
 * Copyright (c) 2026 Oracle and/or its affiliates.
 * Licensed under the Universal Permissive License v 1.0 as shown at
 * https://oss.oracle.com/licenses/upl/
 *
 * SPDX-License-Identifier: UPL-1.0
 */

#include "freertos/FreeRTOS.h"

#include "freertos/event_groups.h"
#include "freertos/task.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>

#include "bsp/m5stack_core_s3.h"
#include "cJSON.h"
#include "config_manager.h"
#include "display_manager.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_timer.h"
#include "mqtt_manager.h"
#include "network_manager.h"
#include "sensor_manager.h"
#include "update_manager.h"

static const char *TAG = "app_main";
static iot_config_t s_iot_config;
static iot_certs_t s_iot_certs;
static QueueHandle_t mqtt_event_data_queue;

/**
 * Restart the device with a countdown.
 */
static void reboot_device()
{
    char buf[64];
    for (uint8_t i = 5; i > 0; i--) {
        snprintf(buf, sizeof(buf), "Firmware update completed\nRestart in %u second%c", i, i > 1 ? 's' : ' ');
        show_status_message(buf);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    esp_restart();
}

/**
 * Render sensor readings on the display.
 */
static void show_sensor_data(const sensor_data_t *data)
{
    char buffer[160];
    if (!data) {
        return;
    }
    int offset = 0;
    if (data->sht_valid) {
        offset += snprintf(buffer + offset, sizeof(buffer) - offset, "SHT: %.1f°C\nHumidity: %.1f %%",
                           data->sht_temperature_c, data->humidity_percent);
    }
    if (data->qmp_valid && offset < (int) sizeof(buffer)) {
        offset += snprintf(buffer + offset, sizeof(buffer) - offset, "%sQMP: %.1f°C\nPressure: %.1f hPa",
                           offset > 0 ? "\n" : "", data->qmp_temperature_c, data->pressure_hpa);
    }
    if (offset == 0) {
        strlcpy(buffer, "No sensor data", sizeof(buffer));
    }
    show_data(buffer);
}

/**
 * Serialize and publish telemetry data.
 */
static esp_err_t publish_sensor_data(const sensor_data_t *data)
{
    static uint64_t publish_count = 1;
    struct timeval tv;
    gettimeofday(&tv, NULL);
    uint64_t timestamp = (uint64_t) tv.tv_sec * 1000000L + tv.tv_usec;

    cJSON *root = cJSON_CreateObject();
    ESP_RETURN_ON_FALSE(root, ESP_ERR_NO_MEM, TAG, "cJSON_CreateObject()");

    cJSON_AddNumberToObject(root, "time", (double) timestamp);
    if (data->sht_valid) {
        cJSON_AddNumberToObject(root, "sht_temperature", data->sht_temperature_c);
        cJSON_AddNumberToObject(root, "humidity", data->humidity_percent);
    }
    if (data->qmp_valid) {
        cJSON_AddNumberToObject(root, "qmp_temperature", data->qmp_temperature_c);
        cJSON_AddNumberToObject(root, "pressure", data->pressure_hpa);
    }
    cJSON_AddNumberToObject(root, "count", (double) publish_count);

    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    ESP_RETURN_ON_FALSE(payload, ESP_ERR_NO_MEM, TAG, "cJSON_PrintUnformatted()");

    esp_err_t ret = publish_telemetry(payload);
    if (ret == ESP_OK) {
        publish_count++;
    }
    free(payload);
    return ret;
}

/**
 * Sensor sampling task loop.
 */
static void sensors_task(void *pvParameters)
{
    uint16_t publish_freq = *((uint16_t *) pvParameters);
    free(pvParameters);
    while (1) {
        sensor_data_t sensor_data;
        if (env_sensors_read(&sensor_data) == ESP_OK) {
            ESP_LOGI(TAG, "Sensor read complete: sht=%s qmp=%s", sensor_data.sht_valid ? "ok" : "missing",
                     sensor_data.qmp_valid ? "ok" : "missing");
            show_sensor_data(&sensor_data);
            publish_sensor_data(&sensor_data);
        } else {
            ESP_LOGW(TAG, "Failed to read sensors");
        }
        vTaskDelay(pdMS_TO_TICKS(publish_freq * 1000));
    }
}

/**
 * Handle incoming MQTT commands.
 */
void mqtt_command_handler(void *pvParameters)
{
    QueueHandle_t queue = (QueueHandle_t) pvParameters;
    mqtt_msg_t *command_msg = calloc(1, sizeof(*command_msg));
    if (!command_msg) {
        ESP_LOGE(TAG, "Unable to allocate MQTT command buffer");
        vTaskDelete(NULL);
        return;
    }
    bool reboot = false;

    while (1) {
        if (xQueueReceive(queue, command_msg, portMAX_DELAY)) {
            ESP_LOGI(TAG, "Processing command topic %s (%u bytes)", command_msg->topic,
                     (unsigned) strlen(command_msg->payload));

            cJSON *root = cJSON_Parse(command_msg->payload);
            if (!root) {
                ESP_LOGW(TAG, "Invalid command payload");
                publish_response(command_msg->topic, NULL, "invalid_json");
                continue;
            }
            const cJSON *cmd = cJSON_GetObjectItemCaseSensitive(root, "cmd");
            const char *command_name = (cJSON_IsString(cmd) && cmd->valuestring) ? cmd->valuestring : NULL;
            const char *status = "ignored";
            if (cJSON_IsString(cmd) && cmd->valuestring) {
                if (!strcasecmp(cmd->valuestring, "ota")) {
                    const cJSON *url = cJSON_GetObjectItemCaseSensitive(root, "url");
                    const cJSON *new_version = cJSON_GetObjectItemCaseSensitive(root, "version");

                    if (!cJSON_IsString(url)) {
                        status = "missing_url";
                    } else if (!cJSON_IsString(new_version)) {
                        status = "missing_version";
                    } else if (cJSON_IsString(new_version)) {
                        const esp_app_desc_t *app_desc = esp_app_get_description();

                        // If versions are identical, skip the update
                        if (strcmp(new_version->valuestring, app_desc->version) == 0) {
                            ESP_LOGI(TAG, "Already on version %s. Skipping OTA.", app_desc->version);
                            status = "already_up_to_date";
                        } else {
                            // Versions differ, proceed with update
                            screensaver_turn_on();
                            show_status_message("Firmware update in progress");
                            if (start_https_ota(url->valuestring, s_iot_certs.ota_ca_cert) == ESP_OK) {
                                status = "ota_started";
                                reboot = true;
                            } else {
                                status = "ota_failed";
                                show_status_message("Firmware update failed");
                            }
                        }
                    }
                }

                // Add other commands handling here
            }
            publish_response(command_msg->topic, command_name, status);
            cJSON_Delete(root);
            if (reboot) {
                reboot_device();
            }
        }
    }
}

/**
 * Application entry point.
 */
void app_main(void)
{
    const esp_app_desc_t *app_desc = esp_app_get_description();
    ESP_LOGI(TAG, "Starting main program - %s Version %s", app_desc->project_name, app_desc->version);

    // The M5Stack CoreS3 BSP cannot handle SD Card and LCD screen simultaneously
    // (Version 3.0.2). All SD card operations run before initializing the
    // screen. This section does not abort on error to allow display of an error
    // message.
    esp_err_t bsp_sdcard_ret = bsp_sdcard_mount();

    // Check for firmware update on SD card
    // ESP_OK means an update has been flashed, device needs to reboot
    esp_err_t sd_update_ret = ESP_ERR_NOT_FOUND;
    if (bsp_sdcard_ret == ESP_OK) {
        sd_update_ret = check_for_sd_update();
    } else {
        ESP_LOGW(TAG, "SD card not available: %s", esp_err_to_name(bsp_sdcard_ret));
    }

    // Load configuration from flash or SD
    // Skip if we have a firmware update
    esp_err_t config_init_ret = ESP_FAIL;
    if (sd_update_ret != ESP_OK) {
        if (sd_update_ret == ESP_ERR_NOT_FOUND) {
            ESP_LOGI(TAG, "SD update check: no update available");
        } else {
            ESP_LOGW(TAG, "SD update failed: %s", esp_err_to_name(sd_update_ret));
        }
        config_init_ret = config_manager_init(&s_iot_config, &s_iot_certs);
        if (config_init_ret != ESP_OK) {
            ESP_LOGE(TAG, "Configuration unavailable (%s)", esp_err_to_name(config_init_ret));
        }
    }

    // All SD card operations done, unmount and start LCD
    if (bsp_sdcard_ret == ESP_OK) {
        bsp_sdcard_unmount();
    }
    bsp_i2c_init();
    display_start(s_iot_config.hardware.display_brightness);
    show_splash_screen(5000);
    display_screensaver_init(s_iot_config.hardware.display_timeout, s_iot_config.hardware.display_brightness);

    // Handle pre-display messages
    if (sd_update_ret == ESP_OK) {
        reboot_device();
    }
    if (config_init_ret != ESP_OK) {
        show_status_message("No valid configuration loaded\nAborting");
        return;
    } else {
        show_status_message("Configuration loaded");
        vTaskDelay(pdMS_TO_TICKS(1000));
    }

    esp_ota_img_states_t ota_state;
    if (esp_ota_get_state_partition(esp_ota_get_running_partition(), &ota_state) == ESP_OK) {
        if (ota_state == ESP_OTA_IMG_PENDING_VERIFY) {
            if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) {
                ESP_LOGI("OTA", "App verified! Rollback cancelled.");
                show_status_message("New firmware installed");
                vTaskDelay(pdMS_TO_TICKS(1000));
            } else {
                ESP_LOGE("OTA", "Failed to cancel rollback! Device will revert on next reboot.");
            }
        }
    }

    show_status_message("Connecting Wi-Fi");
    if (wifi_connect(s_iot_config.wifi.ssid, s_iot_config.wifi.password) == ESP_OK) {
        show_status_message("Wi-Fi connected");
        vTaskDelay(pdMS_TO_TICKS(1000));
    } else {
        show_status_message("Wi-Fi failed\nCheck configuration");
        return;
    }

    show_status_message("Starting time sync");
    if (wait_for_time_sync() == ESP_OK) {
        show_status_message("Time synced");
    } else {
        show_status_message("Time sync failed");
    }
    vTaskDelay(pdMS_TO_TICKS(1000));

    if (env_sensors_init(s_iot_config.hardware.i2c_port) == ESP_OK) {
        show_status_message("Sensors ready");
        uint16_t *publish_freq = malloc(sizeof(uint16_t));
        if (!publish_freq) {
            show_status_message("Out of memory\nAborting");
            return;
        }
        *publish_freq = s_iot_config.mqtt.publish_freq;
        BaseType_t task_ret =
            xTaskCreatePinnedToCore(sensors_task, "sensors_task", 4096, (void *) publish_freq, 5, NULL, tskNO_AFFINITY);
        if (task_ret != pdPASS) {
            free(publish_freq);
            show_status_message("Sensor task failed\nAborting");
            return;
        }
    } else {
        show_status_message("Sensors initialization failed\nAborting");
        return;
    }

    mqtt_event_data_queue = xQueueCreate(5, sizeof(mqtt_msg_t));
    if (start_mqtt_client(&s_iot_config.mqtt, &s_iot_certs, mqtt_event_data_queue) == ESP_OK) {
        show_status_message("MQTT connecting...");
        xTaskCreate(mqtt_command_handler, "cmd_handler", 4096, (void *) mqtt_event_data_queue, 5, NULL);
    } else {
        show_status_message("MQTT initialization failed");
    }
}
