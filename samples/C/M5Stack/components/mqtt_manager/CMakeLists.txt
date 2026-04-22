idf_component_register(SRCS "mqtt_manager.c"
                       INCLUDE_DIRS "include"
                       REQUIRES ""
                       PRIV_REQUIRES config_manager display_manager esp_event json mqtt
                       )
