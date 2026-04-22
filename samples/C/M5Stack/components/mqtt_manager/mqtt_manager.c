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

#define PREVIEW_SIZE 64

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

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data);
static void build_topic(char *out, size_t len, const char *suffix);

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

    mqtt_state.mqtt_event_group = xEventGroupCreate();
    ESP_RETURN_ON_FALSE(mqtt_state.mqtt_event_group != NULL, ESP_ERR_NO_MEM, TAG, "MQTT event group");

    bool use_tls = (mqtt_config->port == 8883);
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
        if (iot_certs->mqtt_ca_cert) {
            mqtt_cfg.broker.verification.certificate = iot_certs->mqtt_ca_cert;
        } else {
            mqtt_cfg.broker.verification.skip_cert_common_name_check = true;
        }
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
            if (mqtt_state.event_data_queue) {
                mqtt_msg_t command_message;
                size_t topic_len = event->topic_len < (int) sizeof(command_message.topic)
                                       ? (size_t) event->topic_len
                                       : sizeof(command_message.topic) - 1;
                size_t payload_len = event->data_len < (int) sizeof(command_message.payload)
                                         ? (size_t) event->data_len
                                         : sizeof(command_message.payload) - 1;

                memcpy(command_message.topic, event->topic, topic_len);
                command_message.topic[topic_len] = '\0';
                memcpy(command_message.payload, event->data, payload_len);
                command_message.payload[payload_len] = '\0';
                if (xQueueSend(mqtt_state.event_data_queue, &command_message, 0) != pdPASS) {
                    ESP_LOGW("MQTT", "Queue full, message dropped!");
                }
            }
            break;
        default:
            break;
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
esp_err_t publish_response(const char *command_topic, const char *initial_payload, const char *status)
{
    if (!command_topic || !initial_payload || !status) {
        return ESP_ERR_INVALID_ARG;
    }
    char preview[PREVIEW_SIZE] = "";
    strlcpy(preview, initial_payload, sizeof(preview));

    cJSON *root = cJSON_CreateObject();
    ESP_RETURN_ON_FALSE(root, ESP_ERR_NO_MEM, TAG, "cJSON_CreateObject()");
    cJSON_AddStringToObject(root, "status", status[0] == '\0' ? "rsp" : status);
    cJSON_AddStringToObject(root, "original_payload", preview);
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
