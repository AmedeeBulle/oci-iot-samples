/*
 * display_manager.h
 *
 * Manage the M5Stack CoreS3 screen
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

/**
 * Initialize the display subsystem.
 */
void display_start(uint8_t display_brightness);

/**
 * Show the splash screen for a duration.
 */
void show_splash_screen(uint32_t time_ms);

/**
 * Initialize screen saver handling.
 */
void display_screensaver_init(uint16_t timeout_seconds, uint8_t display_brightness);

/**
 * Turn on the display backlight.
 */
void screensaver_turn_on(void);

/**
 * Display a status message.
 */
void show_status_message(const char *message);

/**
 * Display sensor data content.
 */
void show_data(const char *data);
