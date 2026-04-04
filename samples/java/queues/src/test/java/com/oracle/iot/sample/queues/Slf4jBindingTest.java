package com.oracle.iot.sample.queues;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;

import org.junit.jupiter.api.Test;

class Slf4jBindingTest {

    @Test
    void slf4jBindingIsPresentOnRuntimeClasspath() {
        assertDoesNotThrow(() -> Class.forName("org.slf4j.impl.StaticLoggerBinder"));
    }
}
