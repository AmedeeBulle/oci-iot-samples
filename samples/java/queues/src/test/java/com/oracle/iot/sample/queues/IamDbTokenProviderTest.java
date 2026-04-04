package com.oracle.iot.sample.queues;

import static org.junit.jupiter.api.Assertions.assertFalse;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

class IamDbTokenProviderTest {

    @Test
    void sourceDoesNotUseDeprecatedDataplaneClientConstructor() throws IOException {
        String source = Files.readString(Path.of(
                "src/main/java/com/oracle/iot/sample/queues/IamDbTokenProvider.java"));

        assertFalse(source.contains("new DataplaneClient("));
    }
}
