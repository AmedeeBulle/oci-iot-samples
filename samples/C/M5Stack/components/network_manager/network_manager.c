/*
 * network_manager.c
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

#include "network_manager.h"

#include <string.h>
#include <time.h>

#include "esp_attr.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_sntp.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "nvs_flash.h"

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT BIT1
#define WIFI_MAX_RETRY 5

// Additional time server if there is a free slot available
#define SNTP_SERVER "time.google.com"

static const char *TAG = "network_manager";

typedef struct {
    EventGroupHandle_t wifi_event_group;
    int wifi_retry_count;
} network_state_t;

static network_state_t network_state = {
    .wifi_event_group = NULL,
    .wifi_retry_count = 0,
};

static void init_sntp();

/**
 * Initialize NVS storage.
 */
static esp_err_t init_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_RETURN_ON_ERROR(nvs_flash_erase(), TAG, "erase nvs");
        err = nvs_flash_init();
    }
    return err;
}

/**
 * Handle Wi-Fi and IP events.
 */
static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        if (network_state.wifi_retry_count < WIFI_MAX_RETRY) {
            esp_wifi_connect();
            network_state.wifi_retry_count++;
            ESP_LOGW(TAG, "Retrying Wi-Fi connection (%d)", network_state.wifi_retry_count);
        } else {
            xEventGroupSetBits(network_state.wifi_event_group, WIFI_FAIL_BIT);
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *) event_data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        network_state.wifi_retry_count = 0;
        xEventGroupSetBits(network_state.wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

/**
 * Connect to a Wi-Fi network.
 */
esp_err_t wifi_connect(const char *ssid, const char *password)
{
    if (!ssid || ssid[0] == '\0' || !password || password[0] == '\0') {
        ESP_LOGE(TAG, "Wi-Fi SSID missing in configuration");
        return ESP_ERR_INVALID_ARG;
    }

    ESP_RETURN_ON_ERROR(init_nvs(), TAG, "NVS flash init");

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_err_t err = esp_netif_init();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }
    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }
    esp_netif_create_default_wifi_sta();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&cfg), TAG, "Wi-Fi init");

    if (!network_state.wifi_event_group) {
        network_state.wifi_event_group = xEventGroupCreate();
        ESP_RETURN_ON_FALSE(network_state.wifi_event_group != NULL, ESP_ERR_NO_MEM, TAG, "event group");
    }

    wifi_config_t wifi_cfg = {0};
    strncpy((char *) wifi_cfg.sta.ssid, ssid, sizeof(wifi_cfg.sta.ssid));
    strncpy((char *) wifi_cfg.sta.password, password, sizeof(wifi_cfg.sta.password));
    wifi_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    ESP_RETURN_ON_ERROR(
        esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL, &instance_any_id),
        TAG, "Register Wi-Fi handler");
    ESP_RETURN_ON_ERROR(
        esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL, &instance_got_ip),
        TAG, "Register IP handler");

    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "Set Wi-Fi mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg), TAG, "Set Wi-Fi config");

    // Initialize SNTP -- must be after the TCP/IP stack is initialized, but before the DHCP handshake
    init_sntp();

    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "Wi-Fi start");

    EventBits_t bits = xEventGroupWaitBits(network_state.wifi_event_group, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT, pdTRUE,
                                           pdFALSE, pdMS_TO_TICKS(30000));

    ESP_ERROR_CHECK(esp_event_handler_instance_unregister(IP_EVENT, IP_EVENT_STA_GOT_IP, instance_got_ip));
    ESP_ERROR_CHECK(esp_event_handler_instance_unregister(WIFI_EVENT, ESP_EVENT_ANY_ID, instance_any_id));

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "Connected to %s", ssid);
        return ESP_OK;
    } else if (bits & WIFI_FAIL_BIT) {
        ESP_LOGE(TAG, "Failed to connect to %s", ssid);
        return ESP_ERR_TIMEOUT;
    }

    ESP_LOGE(TAG, "Wi-Fi wait timed out");
    return ESP_ERR_TIMEOUT;
}

/**
 * Log SNTP servers
 */
static void log_sntp_servers(void)
{
    ESP_LOGI(TAG, "Configured NTP servers:");

    for (uint8_t i = 0; i < SNTP_MAX_SERVERS; ++i) {
        if (esp_sntp_getservername(i)) {
            ESP_LOGI(TAG, "server %d: %s", i, esp_sntp_getservername(i));
        } else {
            // Fallback to IP
            char buff[48];
            ip_addr_t const *ip = esp_sntp_getserver(i);
            if (ipaddr_ntoa_r(ip, buff, sizeof(buff)) != NULL) {
                ESP_LOGI(TAG, "server %d: %s", i, buff);
            }
        }
    }
}

/**
 * Wait until SNTP sync completes.
 */
void wait_for_time_sync()
{
    int retry = 0;
    const int retry_count = 15;

    esp_netif_sntp_start();
    log_sntp_servers();
    while (sntp_get_sync_status() == SNTP_SYNC_STATUS_RESET && retry++ < retry_count) {
        ESP_LOGI("TAG", "Waiting for system time to be set... (%d/%d)", retry, retry_count);
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}

/**
 * Initialize SNTP time sync.
 */
static void init_sntp()
{
    ESP_LOGI(TAG, "Initializing SNTP");
#if LWIP_DHCP_GET_NTP_SRV
    // Get NTP server from DHCP - Backup: configured server
    esp_sntp_config_t config = ESP_NETIF_SNTP_DEFAULT_CONFIG(CONFIG_SNTP_TIME_SERVER);
    config.server_from_dhcp = true;
    config.renew_servers_after_new_IP = true;
    config.index_of_first_server = 1;
#else /* LWIP_DHCP_GET_NTP_SRV */
#if CONFIG_LWIP_SNTP_MAX_SERVERS > 1
    // Static config: configured server + backup
    esp_sntp_config_t config =
        ESP_NETIF_SNTP_DEFAULT_CONFIG_MULTIPLE(2, ESP_SNTP_SERVER_LIST(CONFIG_SNTP_TIME_SERVER, SNTP_SERVER));
#else  /* CONFIG_LWIP_SNTP_MAX_SERVERS */
    // Static config, single server: use the one in configuration
    esp_sntp_config_t config = ESP_NETIF_SNTP_DEFAULT_CONFIG(CONFIG_SNTP_TIME_SERVER);
#endif /* CONFIG_LWIP_SNTP_MAX_SERVERS */
#endif /* LWIP_DHCP_GET_NTP_SRV */
    config.start = false;
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
    esp_netif_sntp_init(&config);
}
