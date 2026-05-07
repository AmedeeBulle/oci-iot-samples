/*
 * mqtt_manager.c
 *
 * Handle MQTT messaging
 *
 * Copyright (c) 2026 Oracle and/or its affiliates.
 * Licensed under the Universal Permissive License v 1.0 as shown at
 * https://oss.oracle.com/licenses/upl/
 *
 * SPDX-License-Identifier: UPL-1.0
 */

#include "freertos/FreeRTOS.h"

#include "mqtt_manager.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "freertos/queue.h"

#include "cJSON.h"
#include "config_manager.h"
#include "display_manager.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_event.h"
#include "mqtt_client.h"

#define MQTT_TOPIC_TELEMETRY "telemetry"
#define MQTT_TOPIC_COMMAND "cmd"
#define MQTT_TOPIC_RSP "rsp"

#define MQTT_CONNECTED_BIT BIT0

static const char *TAG = "mqtt_manager";

typedef struct {
    EventGroupHandle_t mqtt_event_group;
    esp_mqtt_client_handle_t mqtt_client;
    QueueHandle_t event_data_queue;
    uint8_t qos;
    char topic[CONFIG_MGR_MAX_TOPIC_LEN];
} mqtt_state_t;

static mqtt_state_t mqtt_state = {
    .mqtt_event_group = NULL,
    .mqtt_client = NULL,
    .event_data_queue = NULL,
    .qos = 0,
    .topic = "",
};

typedef struct {
    mqtt_msg_t msg;
    int total_len;
    int received_len;
    bool active;
    bool dropping;
} mqtt_command_assembly_t;

static mqtt_command_assembly_t command_assembly = {0};

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data);
static void build_topic(char *out, size_t len, const char *suffix);
static void handle_mqtt_data(esp_mqtt_event_handle_t event);

/**
 * Initialize and start the MQTT client.
 */
esp_err_t start_mqtt_client(mqtt_config_t *mqtt_config, iot_certs_t *iot_certs, QueueHandle_t event_data_queue)
{
    ESP_RETURN_ON_FALSE(mqtt_config && iot_certs, ESP_ERR_INVALID_ARG, TAG, "Null argument not allowed");
    ESP_RETURN_ON_FALSE(mqtt_config->host[0], ESP_ERR_INVALID_ARG, TAG, "MQTT host missing in configuration");
    strlcpy(mqtt_state.topic, mqtt_config->topic, sizeof(mqtt_state.topic));
    mqtt_state.qos = mqtt_config->qos;
    mqtt_state.event_data_queue = event_data_queue;

    bool use_tls = (mqtt_config->port == 8883);
    if (use_tls && !iot_certs->mqtt_ca_cert) {
        ESP_LOGE(TAG, "MQTT CA certificate missing for TLS connection");
        return ESP_ERR_INVALID_STATE;
    }

    mqtt_state.mqtt_event_group = xEventGroupCreate();
    ESP_RETURN_ON_FALSE(mqtt_state.mqtt_event_group != NULL, ESP_ERR_NO_MEM, TAG, "MQTT event group");

    esp_mqtt_client_config_t mqtt_cfg = {
        .broker =
            {
                .address.hostname = mqtt_config->host,
                .address.port = mqtt_config->port,
                .address.transport = use_tls ? MQTT_TRANSPORT_OVER_SSL : MQTT_TRANSPORT_OVER_TCP,
            },
        .credentials.client_id = (mqtt_config->user[0] != '\0') ? mqtt_config->user : NULL,
        .session = {
            .disable_clean_session = true,
            .keepalive = mqtt_config->keep_alive,
        }};

    if (use_tls) {
        mqtt_cfg.broker.verification.certificate = iot_certs->mqtt_ca_cert;
    }

    if (mqtt_config->password[0] != '\0') {
        mqtt_cfg.credentials.username = mqtt_config->user;
        mqtt_cfg.credentials.authentication.password = mqtt_config->password;
    } else if (iot_certs->client_cert && iot_certs->client_key) {
        mqtt_cfg.credentials.authentication.certificate = iot_certs->client_cert;
        mqtt_cfg.credentials.authentication.key = iot_certs->client_key;
    }

    mqtt_state.mqtt_client = esp_mqtt_client_init(&mqtt_cfg);
    ESP_RETURN_ON_FALSE(mqtt_state.mqtt_client != NULL, ESP_FAIL, TAG, "MQTT client init");
    ESP_RETURN_ON_ERROR(
        esp_mqtt_client_register_event(mqtt_state.mqtt_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL), TAG,
        "MQTT register event");

    ESP_RETURN_ON_ERROR(esp_mqtt_client_start(mqtt_state.mqtt_client), TAG, "MQTT start");
    return ESP_OK;
}

/**
 * Handle MQTT client events.
 */
static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)
{
    esp_mqtt_event_handle_t event = event_data;
    switch (event_id) {
        case MQTT_EVENT_CONNECTED: {
            ESP_LOGI(TAG, "MQTT connected");
            if (mqtt_state.mqtt_event_group) {
                xEventGroupSetBits(mqtt_state.mqtt_event_group, MQTT_CONNECTED_BIT);
            }
            char cmd_topic[CONFIG_MGR_MAX_TOPIC_LEN + sizeof(MQTT_TOPIC_COMMAND) + 1];
            build_topic(cmd_topic, sizeof(cmd_topic), MQTT_TOPIC_COMMAND "/+");
            esp_mqtt_client_subscribe(mqtt_state.mqtt_client, cmd_topic, 1);
            show_status_message("MQTT connected");
            break;
        }
        case MQTT_EVENT_DISCONNECTED: {
            ESP_LOGW(TAG, "MQTT disconnected");
            if (mqtt_state.mqtt_event_group) {
                xEventGroupClearBits(mqtt_state.mqtt_event_group, MQTT_CONNECTED_BIT);
            }
            show_status_message("MQTT disconnected");
            break;
        }
        case MQTT_EVENT_DATA:
            handle_mqtt_data(event);
            break;
        default:
            break;
    }
}

/**
 * Buffer MQTT command data until the full payload is available.
 */
static void handle_mqtt_data(esp_mqtt_event_handle_t event)
{
    if (!mqtt_state.event_data_queue || !event) {
        return;
    }

    if (event->current_data_offset == 0) {
        memset(&command_assembly, 0, sizeof(command_assembly));
        if ((event->topic_len > 0 && !event->topic) || (event->data_len > 0 && !event->data)) {
            ESP_LOGW(TAG, "Dropping MQTT command with missing event buffers");
            return;
        }
        if (event->topic_len >= (int) sizeof(command_assembly.msg.topic) ||
            event->total_data_len >= (int) sizeof(command_assembly.msg.payload)) {
            ESP_LOGW(TAG, "Dropping oversized command: topic_len=%d payload_len=%d", event->topic_len,
                     event->total_data_len);
            command_assembly.dropping = true;
            command_assembly.total_len = event->total_data_len;
            return;
        }

        memcpy(command_assembly.msg.topic, event->topic, event->topic_len);
        command_assembly.msg.topic[event->topic_len] = '\0';
        command_assembly.total_len = event->total_data_len;
        command_assembly.active = true;
    } else if (command_assembly.dropping) {
        if (event->current_data_offset + event->data_len >= command_assembly.total_len) {
            memset(&command_assembly, 0, sizeof(command_assembly));
        }
        return;
    } else if (!command_assembly.active) {
        ESP_LOGW(TAG, "Dropping MQTT command fragment without initial chunk");
        return;
    }

    if (event->data_len > 0 && !event->data) {
        ESP_LOGW(TAG, "Dropping MQTT command fragment with missing data buffer");
        memset(&command_assembly, 0, sizeof(command_assembly));
        return;
    }

    if (event->current_data_offset < 0 || event->data_len < 0 ||
        event->current_data_offset + event->data_len > command_assembly.total_len ||
        event->current_data_offset + event->data_len >= (int) sizeof(command_assembly.msg.payload)) {
        ESP_LOGW(TAG, "Dropping invalid MQTT command fragment: offset=%d len=%d total=%d",
                 event->current_data_offset, event->data_len, command_assembly.total_len);
        memset(&command_assembly, 0, sizeof(command_assembly));
        return;
    }

    memcpy(command_assembly.msg.payload + event->current_data_offset, event->data, event->data_len);
    command_assembly.received_len += event->data_len;

    if (event->current_data_offset + event->data_len == command_assembly.total_len) {
        command_assembly.msg.payload[command_assembly.total_len] = '\0';
        if (command_assembly.received_len != command_assembly.total_len) {
            ESP_LOGW(TAG, "Dropping incomplete MQTT command: received=%d total=%d", command_assembly.received_len,
                     command_assembly.total_len);
            memset(&command_assembly, 0, sizeof(command_assembly));
            return;
        }
        if (xQueueSend(mqtt_state.event_data_queue, &command_assembly.msg, 0) != pdPASS) {
            ESP_LOGW(TAG, "Queue full, command dropped");
        }
        memset(&command_assembly, 0, sizeof(command_assembly));
    }
}

/**
 * Build a topic string with a suffix.
 */
static void build_topic(char *out, size_t len, const char *suffix)
{
    if (!out || len == 0) {
        return;
    }
    out[0] = '\0';
    const char *base = mqtt_state.topic;
    if (base[0] == '\0') {
        if (suffix) {
            strlcpy(out, suffix, len);
        }
        return;
    }
    bool base_has_slash = base[strlen(base) - 1] == '/';
    const char *suffix_str = (suffix && suffix[0] == '/') ? suffix + 1 : suffix;
    if (!suffix_str || suffix_str[0] == '\0') {
        strlcpy(out, base, len);
        return;
    }
    snprintf(out, len, "%s%s%s", base, base_has_slash ? "" : "/", suffix_str);
}

/**
 * Publish a message to a topic suffix.
 */
static esp_err_t publish_message(const char *topic_suffix, const char *payload)
{
    if (!topic_suffix || topic_suffix[0] == '\0' || !payload || payload[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }
    if (!mqtt_state.mqtt_client || !mqtt_state.mqtt_event_group) {
        return ESP_ERR_INVALID_STATE;
    }
    if ((xEventGroupGetBits(mqtt_state.mqtt_event_group) & MQTT_CONNECTED_BIT) == 0) {
        return ESP_FAIL;
    }
    // Build final topic
    // It will be at most length of prefix + separator + length of suffix + null
    size_t topic_size = strlen(mqtt_state.topic) + strlen(topic_suffix) + 2;
    char *topic;
    ESP_RETURN_ON_FALSE(topic = malloc(topic_size), ESP_ERR_NO_MEM, TAG, "malloc(topic)");
    bool prefix_has_slash = mqtt_state.topic[0] != '\0' && mqtt_state.topic[strlen(mqtt_state.topic) - 1] == '/';
    const char *suffix = topic_suffix[0] == '/' ? topic_suffix + 1 : topic_suffix;
    snprintf(topic, topic_size, "%s%s%s", mqtt_state.topic, prefix_has_slash ? "" : "/", suffix);
    int ret = esp_mqtt_client_publish(mqtt_state.mqtt_client, topic, payload, 0, mqtt_state.qos, 0);
    free(topic);
    return ret < 0 ? ESP_FAIL : ESP_OK;
}

/**
 * Publish a response message.
 */
esp_err_t publish_response(const char *command_topic, const char *command_name, const char *status)
{
    if (!command_topic || !status) {
        return ESP_ERR_INVALID_ARG;
    }

    cJSON *root = cJSON_CreateObject();
    ESP_RETURN_ON_FALSE(root, ESP_ERR_NO_MEM, TAG, "cJSON_CreateObject()");
    cJSON_AddStringToObject(root, "status", status[0] == '\0' ? "rsp" : status);
    if (command_name && command_name[0] != '\0') {
        cJSON_AddStringToObject(root, "command", command_name);
    }
    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    // Find last component of the topic
    const char *key = strrchr(command_topic, '/');
    esp_err_t ret;
    if (!key || key[1] == '\0') {
        // Shouldn't happen given the subscribe pattern -- send a response without suffix
        ret = publish_message(MQTT_TOPIC_RSP, payload);
    } else {
        key++;
        // topic will be length of MQTT_TOPIC_RSP + separator + length of key + null
        size_t topic_size = strlen(MQTT_TOPIC_RSP) + strlen(key) + 2;
        char *topic;
        topic = malloc(topic_size);
        if (topic) {
            snprintf(topic, topic_size, "%s/%s", MQTT_TOPIC_RSP, key);
            ret = publish_message(topic, payload);
            free(topic);
        } else {
            ret = ESP_ERR_NO_MEM;
        }
    }
    free(payload);
    return ret;
}

/**
 * Publish an telemetry message.
 */
esp_err_t publish_telemetry(const char *payload) { return publish_message(MQTT_TOPIC_TELEMETRY, payload); }
