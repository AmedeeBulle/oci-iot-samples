idf_component_register(SRCS "sensor_manager.c"
                       INCLUDE_DIRS "include"
                       REQUIRES ""
                       PRIV_REQUIRES driver espressif__m5stack_core_s3 espressif__sht3x qmp6988 sht3x)
