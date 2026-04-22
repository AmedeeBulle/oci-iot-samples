/*
 * display_manager.c
 *
 * Manage the M5Stack CoreS3 screen
 *
 * Copyright (c) 2026 Oracle and/or its affiliates.
 * Licensed under the Universal Permissive License v 1.0 as shown at
 * https://oss.oracle.com/licenses/upl/
 *
 * SPDX-License-Identifier: UPL-1.0
 */

#include "freertos/FreeRTOS.h"

#include "display_manager.h"

#include "freertos/task.h"

#include <stdbool.h>

#include "bsp/m5stack_core_s3.h"
#include "esp_log.h"
#include "esp_lvgl_port.h"
#include "esp_ota_ops.h"
#include "esp_timer.h"
#include "lvgl.h"

LV_IMG_DECLARE(m5_splash)
LV_IMG_DECLARE(oci_iot_platform)

static const char *TAG = "display_manager";

typedef struct {
    esp_timer_handle_t screensaver_timer;
    uint32_t screensaver_timeout_ms;
    uint8_t display_brightness;
    bool backlight_on;
    lv_indev_t *touch_indev;
} display_state_t;

static display_state_t display_state;

static void screensaver_turn_off(void);
static void screensaver_restart_timer(void);
static void screensaver_timeout_cb(void *arg);
static void screensaver_touch_event_cb(lv_event_t *event);

/**
 * Initialize the display subsystem.
 */
void display_start(uint8_t display_brightness)
{
    lv_display_t *display = bsp_display_start();
    (void) display;
    bsp_display_brightness_set(display_brightness);
}

/**
 * Show the splash screen for a duration.
 */
void show_splash_screen(uint32_t time_ms)
{
    lvgl_port_lock(0);
    lv_obj_t *splash_img = lv_image_create(lv_screen_active());
    lv_image_set_src(splash_img, &m5_splash);
    lv_obj_center(splash_img);
    lvgl_port_unlock();
    vTaskDelay(pdMS_TO_TICKS(time_ms));
    lvgl_port_lock(0);
    lv_obj_delete(splash_img);
    lvgl_port_unlock();

    lvgl_port_lock(0);
    lv_obj_t *title_bar = lv_image_create(lv_screen_active());
    lv_image_set_src(title_bar, &oci_iot_platform);
    lv_obj_align(title_bar, LV_ALIGN_TOP_MID, 0, 0);
    lvgl_port_unlock();

    char bottom_text[80];
    const esp_app_desc_t *app_desc = esp_app_get_description();
    snprintf(bottom_text, sizeof(bottom_text), "%s - %s", app_desc->project_name, app_desc->version);
    lvgl_port_lock(0);
    // Bar Container
    lv_obj_t *bottom_bar = lv_obj_create(lv_scr_act());
    lv_obj_set_size(bottom_bar, lv_pct(100), 40);
    lv_obj_align(bottom_bar, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_set_style_bg_color(bottom_bar, lv_color_make(0xED, 0xEA, 0xE7), 0);
    lv_obj_set_style_bg_opa(bottom_bar, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(bottom_bar, 0, 0);
    lv_obj_set_style_radius(bottom_bar, 0, 0);
    // Label inside the Bar
    lv_obj_t *label = lv_label_create(bottom_bar);
    lv_label_set_text(label, bottom_text);
    lv_obj_center(label);
    lvgl_port_unlock();
}

/**
 * Initialize screen saver handling.
 */
void display_screensaver_init(uint16_t timeout_seconds, uint8_t display_brightness)
{
    display_state.screensaver_timeout_ms = (uint32_t) timeout_seconds * 1000U;
    display_state.display_brightness = display_brightness;
    display_state.backlight_on = true;

    if (display_state.screensaver_timeout_ms == 0) {
        return;
    }

    if (!display_state.screensaver_timer) {
        const esp_timer_create_args_t timer_args = {
            .callback = screensaver_timeout_cb,
            .arg = NULL,
            .dispatch_method = ESP_TIMER_TASK,
            .name = "screen_saver",
        };
        ESP_ERROR_CHECK(esp_timer_create(&timer_args, &display_state.screensaver_timer));
    }

    display_state.touch_indev = bsp_display_get_input_dev();
    if (display_state.touch_indev) {
        lv_indev_add_event_cb(display_state.touch_indev, screensaver_touch_event_cb, LV_EVENT_PRESSED, NULL);
    } else {
        ESP_LOGW(TAG, "Touch input device not available");
    }

    screensaver_restart_timer();
}

/**
 * Display a status message.
 */
void show_status_message(const char *message)
{
    static lv_obj_t *status_label = NULL;

    if (!message) {
        return;
    }
    lvgl_port_lock(0);
    if (!status_label) {
        status_label = lv_label_create(lv_screen_active());
    }
    lv_label_set_text(status_label, message);
    lv_obj_align(status_label, LV_ALIGN_TOP_MID, 0, 70);
    lvgl_port_unlock();
}

/**
 * Display sensor data content.
 */
void show_data(const char *data)
{
    static lv_obj_t *data_label = NULL;

    if (!data) {
        return;
    }
    lvgl_port_lock(0);
    if (!data_label) {
        data_label = lv_label_create(lv_screen_active());
        lv_obj_align(data_label, LV_ALIGN_CENTER, 0, 30);
    }
    lv_label_set_text(data_label, data);
    lvgl_port_unlock();
}

/**
 * Turn off the display backlight.
 */
static void screensaver_turn_off(void)
{
    if (!display_state.backlight_on) {
        return;
    }
    bsp_display_backlight_off();
    display_state.backlight_on = false;
}

/**
 * Turn on the display backlight.
 */
void screensaver_turn_on(void)
{
    if (display_state.backlight_on) {
        return;
    }
    bsp_display_brightness_set(display_state.display_brightness);
    display_state.backlight_on = true;
}

/**
 * Restart the screen saver timer.
 */
static void screensaver_restart_timer(void)
{
    if (!display_state.screensaver_timer || display_state.screensaver_timeout_ms == 0) {
        return;
    }
    esp_timer_stop(display_state.screensaver_timer);
    esp_timer_start_once(display_state.screensaver_timer, (uint64_t) display_state.screensaver_timeout_ms * 1000U);
}

/**
 * Handle screen saver timeout.
 */
static void screensaver_timeout_cb(void *arg)
{
    (void) arg;
    screensaver_turn_off();
}

/**
 * Handle screen tap events.
 */
static void screensaver_touch_event_cb(lv_event_t *event)
{
    (void) event;
    if (display_state.backlight_on) {
        screensaver_turn_off();
    } else {
        screensaver_turn_on();
        screensaver_restart_timer();
    }
}
