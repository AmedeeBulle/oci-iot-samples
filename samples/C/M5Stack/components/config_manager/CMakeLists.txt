idf_component_register(SRCS "config_manager.c"
                       INCLUDE_DIRS "include"
                       REQUIRES ""
                       PRIV_REQUIRES espressif__m5stack_core_s3 driver mbedtls nvs_flash spiffs vfs
                       )
