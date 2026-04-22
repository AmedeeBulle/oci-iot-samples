idf_component_register(SRCS "network_manager.c"
                       INCLUDE_DIRS "include"
                       REQUIRES ""
                       PRIV_REQUIRES esp_event esp_netif esp_wifi nvs_flash
                       )
