idf_component_register(SRCS "sht3x.c"
                    INCLUDE_DIRS "include"
                    REQUIRES esp_driver_i2c
                    PRIV_REQUIRES esp_timer)
