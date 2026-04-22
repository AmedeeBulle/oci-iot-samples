/*
 * sensor_manager.c
 *
 * Sensor abstraction for the ENV III unit (SHT30 + QMP6988)
 *
 * Copyright (c) 2026 Oracle and/or its affiliates.
 * Licensed under the Universal Permissive License v 1.0 as shown at
 * https://oss.oracle.com/licenses/upl/
 *
 * SPDX-License-Identifier: UPL-1.0
 */

#include "sensor_manager.h"

#include <string.h>

#include "bsp/m5stack_core_s3.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"
#include "qmp6988.h"
#include "sht3x.h"

#define TAG "env_sensors"

/*
 * Pin mapping for the A/B ports
 */
#define PORT_A_SDA GPIO_NUM_2
#define PORT_A_SCL GPIO_NUM_1
#define PORT_B_SDA GPIO_NUM_9
#define PORT_B_SCL GPIO_NUM_8

#define I2C_CLK_SPEED_HZ 400000

typedef struct {
    sht3x_t sht_sensor;
    qmp6988_t qmp_sensor;
    bool initialized;
    bool qmp_available;
    bool sht_available;
} sensors_context_t;

static sensors_context_t sensors_context = {{0}, {0}, false, false, false};

/**
 * Initialize the ENV III sensors.
 */
esp_err_t env_sensors_init(char port_sel)
{
    // The BSP initializes the system bus (0). This code initializes the
    // external bus.
    i2c_master_bus_handle_t ext_bus_handle;
    i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_1,
        .sda_io_num = (port_sel == 'A') ? PORT_A_SDA : PORT_B_SDA,
        .scl_io_num = (port_sel == 'A') ? PORT_A_SCL : PORT_B_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_config, &ext_bus_handle));
    ESP_LOGI(TAG, "I2C bus port %d initialized (SDA: GPIO%d, SCL: GPIO%d)", bus_config.i2c_port, bus_config.sda_io_num,
             bus_config.scl_io_num);

    // Initialize SHT3x (ENV III Unit)
    esp_err_t ret = sht3x_init_desc(&sensors_context.sht_sensor, ext_bus_handle, SHT3X_I2C_ADDR_GND, I2C_CLK_SPEED_HZ);
    if (ret == ESP_OK) {
        ret = sht3x_init(&sensors_context.sht_sensor);
        if (ret == ESP_OK) {
            sensors_context.sht_available = true;
            ESP_LOGI(TAG, "✓ ENV III Unit (SHT3x) detected");
        }
    }
    if (!sensors_context.sht_available) {
        ESP_LOGW(TAG, "✗ ENV III Unit (SHT3x) not found");
    }

    // Initialize QMP6988 (ENV III Unit)
    ret = qmp6988_init_desc(&sensors_context.qmp_sensor, ext_bus_handle, QMP6988_I2C_ADDR_GND, I2C_CLK_SPEED_HZ);
    if (ret == ESP_OK) {
        ret = qmp6988_init(&sensors_context.qmp_sensor);
        if (ret == ESP_OK) {
            sensors_context.qmp_available = true;
            ESP_LOGI(TAG, "✓ ENV III Unit (QMP6988) detected");
            ESP_ERROR_CHECK(qmp6988_setup_powermode(&sensors_context.qmp_sensor, QMP6988_NORMAL_MODE));
        }
    }
    if (!sensors_context.qmp_available) {
        ESP_LOGW(TAG, "✗ ENV III Unit (QMP6988) not found");
    }

    if (!sensors_context.qmp_available && !sensors_context.sht_available) {
        ESP_LOGE(TAG, "No sensors detected! Check connections.");
        return ESP_ERR_NOT_FOUND;
    }
    ESP_LOGI(TAG, "Sensors ready");
    sensors_context.initialized = true;
    return ESP_OK;
}

/**
 * Read sensor data from the ENV III sensors.
 */
esp_err_t env_sensors_read(sensor_data_t *sensor_data)
{
    ESP_RETURN_ON_FALSE(sensor_data != NULL, ESP_ERR_INVALID_ARG, TAG, "Null sensor_data");
    ESP_RETURN_ON_FALSE(sensors_context.initialized, ESP_ERR_INVALID_STATE, TAG, "Sensors not initialized");

    if (sensors_context.sht_available) {
        float temperature, humidity;
        esp_err_t err = sht3x_measure(&sensors_context.sht_sensor, &temperature, &humidity);
        if (err == ESP_OK) {
            sensor_data->sht_temperature_c = temperature;
            sensor_data->humidity_percent = humidity;
            ESP_LOGI(TAG, "ENV III - SHT3x:");
            ESP_LOGI(TAG, "  Temperature: %.2f °C", temperature);
            ESP_LOGI(TAG, "  Humidity:    %.2f %%", humidity);
        } else {
            ESP_LOGW(TAG, "ENV III: Read failed for SHT3x sensor: %s", esp_err_to_name(err));
        }
    }

    if (sensors_context.qmp_available) {
        float pressure;
        // Calculate pressure values (this includes temperature as well,
        // as temp is needed to calc pressure
        esp_err_t err = qmp6988_calc_pressure(&sensors_context.qmp_sensor, &pressure);
        if (err == ESP_OK) {
            sensor_data->qmp_temperature_c = sensors_context.qmp_sensor.temperature;
            sensor_data->pressure_hpa = pressure / 100.0f;
            ESP_LOGI(TAG, "ENV III - QMP6988:");
            ESP_LOGI(TAG, "  Temperature: %.2f °C", sensors_context.qmp_sensor.temperature);
            ESP_LOGI(TAG, "  Pressure:    %.2f hPa", pressure / 100.0f);
        } else {
            ESP_LOGW(TAG, "ENV III: Read failed for QMP6988 sensor: %s", esp_err_to_name(err));
        }
    }
    return ESP_OK;
}
