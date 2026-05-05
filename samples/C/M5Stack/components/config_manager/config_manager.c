/*
 * config_manager.c
 *
 * Hardware and main configuration parameters
 *
 * Copyright (c) 2026 Oracle and/or its affiliates.
 * Licensed under the Universal Permissive License v 1.0 as shown at
 * https://oss.oracle.com/licenses/upl/
 *
 * SPDX-License-Identifier: UPL-1.0
 */

#include "config_manager.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "bsp/m5stack_core_s3.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_log.h"
#include "mbedtls/sha256.h"

#define CONFIG_FILENAME "oci-iot.ini"

#define CONFIG_MGR_MAX_FULL_PATH (CONFIG_MGR_MAX_FILE_PATH + 16)

#define IOT_CONFIG_VERSION 1            // Version of the data structure
#define CONFIG_HEADER_MAGIC 0x13040902  // Magic cookie

/*
 * Default values
 */
#define CONFIG_DEFAULT_I2C_PORT 'B'
#define CONFIG_DEFAULT_DISPLAY_BRIGHTNESS 40
#define CONFIG_DEFAULT_DISPLAY_TIMEOUT 300
#define CONFIG_DEFAULT_MQTT_PORT 8883
#define CONFIG_DEFAULT_MQTT_QOS 0
#define CONFIG_DEFAULT_MQTT_KEEP_ALIVE 60
#define CONFIG_DEFAULT_MQTT_TOPIC "iot/v1"
#define CONFIG_DEFAULT_PUBLISH_FREQ 60

/*
 * Certificates file name on SPIFFS
 */
#define CONFIG_CLIENT_CERT_FILENAME "client_cert.pem"
#define CONFIG_CLIENT_KEY_FILENAME "client_key.pem"
#define CONFIG_MQTT_CA_CERT_FILENAME "mqtt_ca_cert.pem"
#define CONFIG_OTA_CA_CERT_FILENAME "ota_ca_cert.pem"

/*
 * Header for saved configuration
 */
typedef struct {
    uint32_t magic;  // Magic number
    uint16_t crc;    // Checksum
} config_header_t;

/*
 * Buffer with header and config
 */
typedef struct {
    config_header_t config_header;
    iot_config_t iot_config;
} config_buffer_t;

static const char *TAG = "config_manager";

/**
 * Mount the SPIFFS partition.
 */
static esp_err_t mount_spiffs(bool *mounted)
{
    if (!mounted) {
        return ESP_ERR_INVALID_ARG;
    }
    *mounted = false;
    esp_err_t ret = bsp_spiffs_mount();
    if (ret == ESP_OK) {
        *mounted = true;
        ESP_LOGI(TAG, "SPIFFS partition mounted");
    } else {
        ESP_LOGW(TAG, "SPIFFS mount failed: %s", esp_err_to_name(ret));
    }
    return ret;
}

/**
 * Unmount the SPIFFS partition.
 */
static void unmount_spiffs(bool mounted)
{
    if (mounted) {
        bsp_spiffs_unmount();
        ESP_LOGI(TAG, "SPIFFS unregistered");
    }
}

/**
 * Compute CCITT CRC-16 for a buffer.
 */
static uint16_t crc16(uint8_t *data, uint16_t len)
{
    // CCITT 16 bits CRC
    // https://www.carnetdumaker.net/articles/les-sommes-de-controle/
    uint16_t crc = 0xFFFF;

    if (len == 0) {
        return 0;
    }

    for (uint16_t i = 0; i < len; i++) {
        uint16_t d_byte = data[i];
        crc ^= d_byte << 8;

        for (uint8_t j = 0; j < 8; j++) {
            uint16_t mix = crc & 0x8000;
            crc = (crc << 1);
            if (mix) {
                crc = crc ^ 0x1021;
            }
        }
    }
    return crc;
}

/**
 * Validate configuration header and CRC.
 */
bool validate_config(config_buffer_t buffer)
{
    if (buffer.config_header.magic != CONFIG_HEADER_MAGIC) {
        ESP_LOGW(TAG, "Invalid magic cookie %#10x", buffer.config_header.magic);
        return false;
    }
    uint16_t crc = crc16((uint8_t *) &(buffer.iot_config), sizeof(iot_config_t));
    if (buffer.config_header.crc != crc) {
        ESP_LOGW(TAG, "Invalid checksum. Expected %#6x got %#6x", crc, buffer.config_header.crc);
        return false;
    }
    return true;
}

/**
 * Load configuration from SPIFFS.
 */
static esp_err_t load_config_from_spiffs(iot_config_t *iot_config)
{
    config_buffer_t config_buffer;
    FILE *f = fopen(BSP_SPIFFS_MOUNT_POINT "/" CONFIG_FILENAME, "rb");
    if (!f) {
        ESP_LOGE(TAG, "Cannot open SPIFFS file %s", CONFIG_FILENAME);
        return ESP_FAIL;
    }
    size_t len = fread(&config_buffer, 1, sizeof(config_buffer), f);
    fclose(f);
    if (len != sizeof(config_buffer) || !validate_config(config_buffer)) {
        ESP_LOGW(TAG, "Invalid data retrieved from SPIFFS");
        return ESP_ERR_INVALID_CRC;
    }
    if (config_buffer.iot_config.version != IOT_CONFIG_VERSION) {
        ESP_LOGW(TAG, "Invalid IoT configuration version retrieved from SPIFFS");
        ESP_LOGW(TAG, "Expected version: %u, got: %u", IOT_CONFIG_VERSION, config_buffer.iot_config.version);
        return ESP_ERR_INVALID_VERSION;
    }
    *iot_config = config_buffer.iot_config;
    return ESP_OK;
}

/**
 * Persist configuration to SPIFFS.
 */
static esp_err_t save_config_to_spiffs(iot_config_t *iot_config)
{
    config_buffer_t config_buffer;
    config_buffer.config_header.magic = CONFIG_HEADER_MAGIC;
    memcpy(&config_buffer.iot_config, iot_config, sizeof(iot_config_t));
    config_buffer.config_header.crc = crc16((uint8_t *) &(config_buffer.iot_config), sizeof(iot_config_t));
    FILE *f = fopen(BSP_SPIFFS_MOUNT_POINT "/" CONFIG_FILENAME, "wb");
    if (!f) {
        ESP_LOGE(TAG, "Cannot open SPIFFS file %s", CONFIG_FILENAME);
        return ESP_FAIL;
    }
    size_t len = fwrite(&config_buffer, 1, sizeof(config_buffer), f);
    fclose(f);
    if (len != sizeof(config_buffer)) {
        ESP_LOGE(TAG, "Cannot save IoT configuration to SPIFFS file %s", CONFIG_FILENAME);
        return ESP_FAIL;
    }
    return ESP_OK;
}

/**
 * Parse a version string.
 */
static uint32_t parse_version(const char *text)
{
    if (!text) {
        return 0;
    }
    return (uint32_t) strtoul(text, NULL, 10);
}

/**
 * Copy a string into a fixed buffer.
 */
static void store_string(char *dst, size_t dst_len, const char *src)
{
    if (!dst || dst_len == 0) {
        return;
    }
    if (!src) {
        dst[0] = '\0';
        return;
    }
    strlcpy(dst, src, dst_len);
}

/**
 * Parse configuration from SD card.
 */
static esp_err_t parse_config_file(iot_config_t *iot_config)
{
    FILE *f = fopen(BSP_SD_MOUNT_POINT "/" CONFIG_FILENAME, "r");
    if (!f) {
        ESP_LOGE(TAG, "Cannot open SD file %s", CONFIG_FILENAME);
        return ESP_FAIL;
    }
    // Initialize config structure with default values
    memset(iot_config, 0, sizeof(*iot_config));
    iot_config->hardware.i2c_port = CONFIG_DEFAULT_I2C_PORT;
    iot_config->hardware.display_brightness = CONFIG_DEFAULT_DISPLAY_BRIGHTNESS;
    iot_config->hardware.display_timeout = CONFIG_DEFAULT_DISPLAY_TIMEOUT;
    iot_config->mqtt.port = CONFIG_DEFAULT_MQTT_PORT;
    iot_config->mqtt.qos = CONFIG_DEFAULT_MQTT_QOS;
    iot_config->mqtt.keep_alive = CONFIG_DEFAULT_MQTT_KEEP_ALIVE;
    strlcpy(iot_config->mqtt.topic, CONFIG_DEFAULT_MQTT_TOPIC, sizeof(iot_config->mqtt.topic));
    iot_config->mqtt.publish_freq = CONFIG_DEFAULT_PUBLISH_FREQ;

    char line[256];
    char section[32] = "";
    while (fgets(line, sizeof(line), f)) {
        char *trim = line;
        while (*trim == ' ' || *trim == '\t') {
            trim++;
        }
        if (*trim == ';' || *trim == '\n' || *trim == '\r' || *trim == '\0') {
            continue;
        }
        if (*trim == '[') {
            char *end = strchr(trim, ']');
            if (end) {
                *end = '\0';
                store_string(section, sizeof(section), trim + 1);
            }
            continue;
        }
        char *eq = strchr(trim, '=');
        if (!eq) {
            continue;
        }
        *eq = '\0';
        char *key = trim;
        int rtrim = strlen(key);
        while (rtrim > 0 && (key[rtrim - 1] == ' ' || key[rtrim - 1] == '\t')) {
            rtrim--;
        }
        key[rtrim] = '\0';
        char *value = eq + 1;
        while (*value == ' ' || *value == '\t') value++;
        char *newline = strpbrk(value, "\r\n");
        if (newline) {
            *newline = '\0';
        }
        rtrim = strlen(value);
        while (rtrim > 0 && (value[rtrim - 1] == ' ' || value[rtrim - 1] == '\t')) {
            rtrim--;
        }
        value[rtrim] = '\0';
        if (strcmp(section, "config") == 0 && strcmp(key, "version") == 0) {
            iot_config->version = parse_version(value);
        } else if (strcmp(section, "hardware") == 0) {
            if (strcmp(key, "i2c_port") == 0) {
                iot_config->hardware.i2c_port = (value[0] == 'A') ? 'A' : 'B';
            } else if (strcmp(key, "display_brightness") == 0) {
                uint8_t brightness = (uint8_t) atoi(value);
                if (brightness > 0 && brightness <= 100) {
                    iot_config->hardware.display_brightness = brightness;
                }
            } else if (strcmp(key, "display_timeout") == 0) {
                uint16_t timeout = (uint16_t) atoi(value);
                if (timeout > 0) {
                    iot_config->hardware.display_timeout = timeout;
                }
            }
        } else if (strcmp(section, "wifi") == 0) {
            if (strcmp(key, "ssid") == 0) {
                store_string(iot_config->wifi.ssid, sizeof(iot_config->wifi.ssid), value);
            } else if (strcmp(key, "password") == 0) {
                store_string(iot_config->wifi.password, sizeof(iot_config->wifi.password), value);
            }
        } else if (strcmp(section, "ota") == 0) {
            if (strcmp(key, "ca_cert") == 0) {
                store_string(iot_config->ota.ca_cert, sizeof(iot_config->ota.ca_cert), value);
            }
        } else if (strcmp(section, "mqtt") == 0) {
            if (strcmp(key, "host") == 0) {
                store_string(iot_config->mqtt.host, sizeof(iot_config->mqtt.host), value);
            } else if (strcmp(key, "port") == 0) {
                iot_config->mqtt.port = (uint16_t) atoi(value);
            } else if (strcmp(key, "qos") == 0) {
                uint8_t qos = (uint8_t) atoi(value);
                if (qos <= 2) {
                    iot_config->mqtt.qos = qos;
                }
            } else if (strcmp(key, "keep_alive") == 0) {
                uint16_t keep_alive = (uint16_t) atoi(value);
                if (keep_alive > 0) {
                    iot_config->mqtt.keep_alive = keep_alive;
                }
            } else if (strcmp(key, "ca_cert") == 0) {
                store_string(iot_config->mqtt.ca_cert, sizeof(iot_config->mqtt.ca_cert), value);
            } else if (strcmp(key, "user") == 0) {
                store_string(iot_config->mqtt.user, sizeof(iot_config->mqtt.user), value);
            } else if (strcmp(key, "password") == 0) {
                store_string(iot_config->mqtt.password, sizeof(iot_config->mqtt.password), value);
            } else if (strcmp(key, "client_cert") == 0) {
                store_string(iot_config->mqtt.client_cert, sizeof(iot_config->mqtt.client_cert), value);
            } else if (strcmp(key, "client_key") == 0) {
                store_string(iot_config->mqtt.client_key, sizeof(iot_config->mqtt.client_key), value);
            } else if (strcmp(key, "topic") == 0) {
                store_string(iot_config->mqtt.topic, sizeof(iot_config->mqtt.topic), value);
            } else if (strcmp(key, "publish_freq") == 0) {
                uint16_t freq = (uint16_t) atoi(value);
                if (freq > 0) {
                    iot_config->mqtt.publish_freq = freq;
                }
            }
        }
    }
    fclose(f);
    if (iot_config->version != IOT_CONFIG_VERSION) {
        ESP_LOGW(TAG, "Invalid IoT configuration version retrieved from SD");
        ESP_LOGW(TAG, "Expected version: %u, got: %u", IOT_CONFIG_VERSION, iot_config->version);
        return ESP_ERR_INVALID_VERSION;
    }
    return ESP_OK;
}

static esp_err_t read_config_from_sd(iot_config_t *iot_config) { return parse_config_file(iot_config); }

/**
 * Copy a file using a fixed-size buffer.
 */
static esp_err_t copy_file_chunked(const char *src_path, const char *dst_path)
{
    FILE *src = fopen(src_path, "rb");
    if (src == NULL) {
        ESP_LOGE(TAG, "Failed to open source: %s", src_path);
        return ESP_ERR_NOT_FOUND;
    }

    FILE *dst = fopen(dst_path, "wb");
    if (dst == NULL) {
        ESP_LOGE(TAG, "Failed to open destination: %s", dst_path);
        fclose(src);
        return ESP_FAIL;
    }

    // 4KB is the internal sector size for most Flash/SPIFFS
    // Using a 4KB buffer aligns with the hardware for better write performance
    const size_t buffer_size = 4096;
    uint8_t *buffer = malloc(buffer_size);
    if (buffer == NULL) {
        ESP_LOGE(TAG, "Memory allocation failed for copy buffer");
        fclose(src);
        fclose(dst);
        return ESP_ERR_NO_MEM;
    }

    size_t bytes_read;
    esp_err_t ret = ESP_OK;

    ESP_LOGI(TAG, "Syncing %s -> %s...", src_path, dst_path);

    while ((bytes_read = fread(buffer, 1, buffer_size, src)) > 0) {
        size_t bytes_written = fwrite(buffer, 1, bytes_read, dst);
        if (bytes_written != bytes_read) {
            ESP_LOGE(TAG, "Write error! Disk full?");
            ret = ESP_FAIL;
            break;
        }
    }
    if (ret == ESP_OK && ferror(src)) {
        ESP_LOGE(TAG, "Read error while copying %s", src_path);
        ret = ESP_FAIL;
    }

    free(buffer);
    fclose(src);
    fclose(dst);

    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "Sync complete.");
    }
    return ret;
}

/**
 * Compute SHA-256 for a file.
 */
static esp_err_t get_file_sha256(const char *path, uint8_t output[32])
{
    FILE *f = fopen(path, "rb");
    if (!f) return ESP_FAIL;

    esp_err_t ret = ESP_OK;
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    if (mbedtls_sha256_starts(&ctx, 0) != 0) {  // 0 for SHA-256
        ret = ESP_FAIL;
        goto cleanup;
    }

    uint8_t buf[512];
    size_t bytes_read;
    while ((bytes_read = fread(buf, 1, sizeof(buf), f)) > 0) {
        if (mbedtls_sha256_update(&ctx, buf, bytes_read) != 0) {
            ret = ESP_FAIL;
            goto cleanup;
        }
    }
    if (ferror(f) || mbedtls_sha256_finish(&ctx, output) != 0) {
        ret = ESP_FAIL;
    }

cleanup:
    mbedtls_sha256_free(&ctx);
    fclose(f);
    return ret;
}

/**
 * Check whether a file differs from SPIFFS.
 */
static esp_err_t needs_update(const char *sd_path, const char *spiffs_path)
{
    struct stat st_sd, st_spiffs;

    // 1. If SD file does not exist, we cannot update
    if (stat(sd_path, &st_sd) != 0) return ESP_ERR_NOT_FOUND;

    // 2. If the SPIFFS file does not exist, we must update
    if (stat(spiffs_path, &st_spiffs) != 0) return ESP_ERR_INVALID_VERSION;

    // 3. Size check (Fastest)
    if (st_sd.st_size != st_spiffs.st_size) return ESP_ERR_INVALID_VERSION;

    // 4. Content check (SHA-256)
    uint8_t hash_sd[32], hash_spiffs[32];
    ESP_RETURN_ON_ERROR(get_file_sha256(sd_path, hash_sd), TAG, "Cannot hash SD file %s", sd_path);
    ESP_RETURN_ON_ERROR(get_file_sha256(spiffs_path, hash_spiffs), TAG, "Cannot hash SPIFFS file %s", spiffs_path);

    return (memcmp(hash_sd, hash_spiffs, 32) == 0) ? ESP_OK : ESP_ERR_INVALID_VERSION;
}

/**
 * Stage a certificate from SD to SPIFFS.
 */
static esp_err_t stage_cert_from_sd(const char *sd_file, const char *spiffs_file)
{
    if (!sd_file || sd_file[0] == '\0') {
        return ESP_OK;
    }
    char sd_path[CONFIG_MGR_MAX_FULL_PATH], spiffs_path[CONFIG_MGR_MAX_FULL_PATH];
    snprintf(sd_path, sizeof(sd_path), "%s/%s", BSP_SD_MOUNT_POINT, sd_file);
    snprintf(spiffs_path, sizeof(spiffs_path), "%s/%s", BSP_SPIFFS_MOUNT_POINT, spiffs_file);
    esp_err_t ret = needs_update(sd_path, spiffs_path);
    if (ret == ESP_ERR_INVALID_VERSION) {
        // Copy file to SPIFFS
        ret = copy_file_chunked(sd_path, spiffs_path);
    }
    // Else: Either no update of file not on SD
    return ret;
}

/**
 * Ensure certificates are staged in SPIFFS.
 */
static esp_err_t ensure_certs(iot_config_t *iot_config)
{
    ESP_RETURN_ON_ERROR(stage_cert_from_sd(iot_config->mqtt.client_cert, CONFIG_CLIENT_CERT_FILENAME), TAG,
                        "Unable to stage Client certificate");
    ESP_RETURN_ON_ERROR(stage_cert_from_sd(iot_config->mqtt.client_key, CONFIG_CLIENT_KEY_FILENAME), TAG,
                        "Unable to stage Client key");
    ESP_RETURN_ON_ERROR(stage_cert_from_sd(iot_config->mqtt.ca_cert, CONFIG_MQTT_CA_CERT_FILENAME), TAG,
                        "Unable to stage MQTT CA certificate");
    ESP_RETURN_ON_ERROR(stage_cert_from_sd(iot_config->ota.ca_cert, CONFIG_OTA_CA_CERT_FILENAME), TAG,
                        "Unable to stage OTA CA certificate");
    return ESP_OK;
}

/**
 * Load a certificate into PSRAM.
 */
static esp_err_t load_certificate_to_psram(const char *sd_file, const char *spiffs_file, char **file_content)
{
    struct stat st;

    *file_content = NULL;

    if (!sd_file || sd_file[0] == '\0') {
        return ESP_OK;
    }
    char spiffs_path[CONFIG_MGR_MAX_FULL_PATH];
    snprintf(spiffs_path, sizeof(spiffs_path), "%s/%s", BSP_SPIFFS_MOUNT_POINT, spiffs_file);

    ESP_RETURN_ON_FALSE(stat(spiffs_path, &st) == 0, ESP_ERR_NOT_FOUND, TAG, "Cannot open %s", spiffs_path);

    ESP_RETURN_ON_FALSE(st.st_size > 0, ESP_ERR_INVALID_SIZE, TAG, "Empty certificate %s", spiffs_path);

    char *buffer = (char *) heap_caps_malloc(st.st_size + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    ESP_RETURN_ON_FALSE(buffer, ESP_ERR_NO_MEM, TAG, "PSRAM allocation failed!");

    FILE *f = fopen(spiffs_path, "rb");
    if (!f) {
        heap_caps_free(buffer);
        ESP_RETURN_ON_ERROR(ESP_ERR_NOT_FOUND, TAG, "Cannot open %s", spiffs_path);
    }
    size_t read_bytes = fread(buffer, 1, st.st_size, f);
    if (read_bytes != (size_t) st.st_size || ferror(f)) {
        fclose(f);
        heap_caps_free(buffer);
        return ESP_FAIL;
    }
    buffer[read_bytes] = '\0';  // Null terminator for PEM strings
    *file_content = buffer;
    fclose(f);
    return ESP_OK;
}

/**
 * Load configured certificates into PSRAM.
 */
static esp_err_t load_certificates_to_psram(iot_config_t *iot_config, iot_certs_t *iot_certs)
{
    ESP_RETURN_ON_ERROR(
        load_certificate_to_psram(iot_config->mqtt.client_cert, CONFIG_CLIENT_CERT_FILENAME, &iot_certs->client_cert),
        TAG, "Unable to load Client certificate");
    ESP_RETURN_ON_ERROR(
        load_certificate_to_psram(iot_config->mqtt.client_key, CONFIG_CLIENT_KEY_FILENAME, &iot_certs->client_key), TAG,
        "Unable to load Client key");
    ESP_RETURN_ON_ERROR(
        load_certificate_to_psram(iot_config->mqtt.ca_cert, CONFIG_MQTT_CA_CERT_FILENAME, &iot_certs->mqtt_ca_cert),
        TAG, "Unable to load MQTT CA certificate");
    if (iot_config->ota.ca_cert[0] == '\0') {
        // OTA CA cert defaults to MQTT CA cert
        iot_certs->ota_ca_cert = iot_certs->mqtt_ca_cert;
    } else {
        ESP_RETURN_ON_ERROR(
            load_certificate_to_psram(iot_config->ota.ca_cert, CONFIG_OTA_CA_CERT_FILENAME, &iot_certs->ota_ca_cert),
            TAG, "Unable to load OTA CA certificate");
    }
    return ESP_OK;
}

/**
 * Log the active configuration.
 */
static void dump_config(iot_config_t *iot_config)
{
    ESP_LOGI(TAG, "Version                : %u", iot_config->version);
    ESP_LOGI(TAG, "I2C port               : %c", iot_config->hardware.i2c_port);
    ESP_LOGI(TAG, "Display brightness     : %u", iot_config->hardware.display_brightness);
    ESP_LOGI(TAG, "Display timeout        : %u", iot_config->hardware.display_timeout);
    ESP_LOGI(TAG, "Wi-Fi SSID             : %s", iot_config->wifi.ssid);
    ESP_LOGI(TAG, "MQTT host              : %s", iot_config->mqtt.host);
    ESP_LOGI(TAG, "MQTT port              : %u", iot_config->mqtt.port);
    ESP_LOGI(TAG, "MQTT QoS               : %u", iot_config->mqtt.qos);
    ESP_LOGI(TAG, "MQTT keep alive        : %u", iot_config->mqtt.keep_alive);
    ESP_LOGI(TAG, "MQTT CA certificate    : %s", iot_config->mqtt.ca_cert);
    ESP_LOGI(TAG, "MQTT user              : %s", iot_config->mqtt.user);
    ESP_LOGI(TAG, "MQTT client certificate: %s", iot_config->mqtt.client_cert);
    ESP_LOGI(TAG, "MQTT client key        : %s", iot_config->mqtt.client_key);
    ESP_LOGI(TAG, "MQTT topic             : %s", iot_config->mqtt.topic);
    ESP_LOGI(TAG, "MQTT publish freq      : %u", iot_config->mqtt.publish_freq);
    ESP_LOGI(TAG, "OTA CA certificate     : %s", iot_config->ota.ca_cert);
}

/**
 * Initialize configuration and certificates.
 */
esp_err_t config_manager_init(iot_config_t *iot_config, iot_certs_t *iot_certs)
{
    if (!iot_config || !iot_certs) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(iot_config, 0, sizeof(iot_config_t));
    memset(iot_certs, 0, sizeof(iot_certs_t));

    bool spiffs_mounted = false;
    ESP_RETURN_ON_ERROR(mount_spiffs(&spiffs_mounted), TAG, "Cannot mount SPIFFS partition");

    bool sd_mounted = (bsp_sdcard_get_handle() != NULL);

    iot_config_t flash_config;
    bool flash_available = (load_config_from_spiffs(&flash_config) == ESP_OK);

    iot_config_t sd_config;
    bool sd_available = (sd_mounted && read_config_from_sd(&sd_config) == ESP_OK);

    esp_err_t ret = ESP_OK;

    // Logic:
    // If we have a (valid) SD config, we use it and if it differs from the
    // SPIFFS config we update the SPIFFS
    if (sd_available) {
        ESP_LOGI(TAG, "Using SD configuration");
        memcpy(iot_config, &sd_config, sizeof(iot_config_t));
        if (!flash_available || memcmp(&sd_config, &flash_config, sizeof(iot_config_t)) != 0) {
            // No SPIFFS configuration or different SPIFFS configuration
            ESP_LOGI(TAG, "Updating SPIFFS configuration");
            ESP_GOTO_ON_ERROR(ret = save_config_to_spiffs(&sd_config), unmount, TAG,
                              "Unable to update configuration in SPIFFS");
        }
        ESP_GOTO_ON_ERROR(ret = ensure_certs(iot_config), unmount, TAG, "Unable to stage certificates on SPIFFS");
    } else if (flash_available) {
        ESP_LOGI(TAG, "Using SPIFFS configuration");
        memcpy(iot_config, &flash_config, sizeof(iot_config_t));
    } else {
        ESP_GOTO_ON_ERROR(ret = ESP_ERR_NOT_FOUND, unmount, TAG,
                          "No configuration found, no data will be sent to the IoT Platform");
    }

    ESP_GOTO_ON_ERROR(ret = load_certificates_to_psram(iot_config, iot_certs), unmount, TAG,
                      "Cannot load certificates into memory");

unmount:
    unmount_spiffs(spiffs_mounted);

    dump_config(iot_config);
    return ret;
}
