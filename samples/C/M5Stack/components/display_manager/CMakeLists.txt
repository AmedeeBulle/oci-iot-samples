idf_component_register(SRCS "display_manager.c"
                       INCLUDE_DIRS "include"
                       REQUIRES ""
                       PRIV_REQUIRES app_update espressif__m5stack_core_s3 esp_timer
                       )
lvgl_port_create_c_image("images/m5_splash.png" "images/" "RGB565" "NONE")
lvgl_port_create_c_image("images/oci_iot_platform.png" "images/" "RGB565" "NONE")
lvgl_port_add_images(${COMPONENT_LIB} "images/")
