package com.oracle.iot.sample.queues;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

import picocli.CommandLine;

class RawQueueSubscriberAppTest {

    @Test
    void rootUsageListsSupportedOptions() {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        CommandLine commandLine = new CommandLine(new RawQueueSubscriberApp(new RawQueueSubscriberApp.NoOpRawQueueOperations()));

        commandLine.usage(new PrintWriter(output, true, StandardCharsets.UTF_8));

        String usage = output.toString(StandardCharsets.UTF_8);
        assertTrue(usage.contains("raw-queue-subscriber"));
        assertTrue(usage.contains("--endpoint"));
        assertTrue(usage.contains("--display-name"));
        assertTrue(usage.contains("--id"));
    }

    @Test
    void cliRejectsIdAndDisplayNameTogether() {
        ByteArrayOutputStream err = new ByteArrayOutputStream();
        CommandLine commandLine = new CommandLine(new RawQueueSubscriberApp(new RawQueueSubscriberApp.NoOpRawQueueOperations()));
        commandLine.setErr(new PrintWriter(err, true, StandardCharsets.UTF_8));

        int exitCode = commandLine.execute("--id", "ocid1.example", "--display-name", "sensor-01");

        assertNotEquals(0, exitCode);
        assertTrue(err.toString(StandardCharsets.UTF_8).contains("mutually exclusive"));
    }

    @Test
    void cliPassesArgumentsToRawQueueService() {
        RecordingRawQueueOperations operations = new RecordingRawQueueOperations();
        CommandLine commandLine = new CommandLine(new RawQueueSubscriberApp(operations));

        int exitCode = commandLine.execute(
                "--config", "samples/java/queues/config.properties",
                "-v",
                "--id", "ocid1.example",
                "--endpoint", "topic/a");

        assertEquals(0, exitCode);
        assertEquals(Path.of("samples/java/queues/config.properties"), operations.configPath);
        assertEquals("ocid1.example", operations.digitalTwinInstanceId);
        assertEquals("topic/a", operations.endpoint);
        assertTrue(operations.verbose);
    }

    private static final class RecordingRawQueueOperations implements RawQueueOperations {
        private Path configPath;
        private String digitalTwinInstanceId;
        private String endpoint;
        private boolean verbose;

        @Override
        public void stream(Path configPath, String digitalTwinInstanceId, String displayName, String endpoint,
                boolean verbose, boolean debug) {
            this.configPath = configPath;
            this.digitalTwinInstanceId = digitalTwinInstanceId;
            this.endpoint = endpoint;
            this.verbose = verbose;
        }
    }
}
