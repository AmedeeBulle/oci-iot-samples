idf_component_register(SRCS "update_manager.c"
                       INCLUDE_DIRS "include"
                       REQUIRES ""
                       PRIV_REQUIRES app_update esp_https_ota espressif__m5stack_core_s3
                       )
