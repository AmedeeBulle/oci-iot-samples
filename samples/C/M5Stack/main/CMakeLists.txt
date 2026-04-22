idf_component_register(SRCS "main.c"
                       INCLUDE_DIRS "."
                       REQUIRES ""
                       PRIV_REQUIRES app_update config_manager display_manager esp_event esp_timer
                       json mqtt_manager sensor_manager update_manager network_manager)
