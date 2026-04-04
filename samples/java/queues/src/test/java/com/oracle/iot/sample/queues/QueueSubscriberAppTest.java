package com.oracle.iot.sample.queues;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.PrintWriter;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;

import org.junit.jupiter.api.Test;

import picocli.CommandLine;

class QueueSubscriberAppTest {

    @Test
    void rootUsageListsSupportedCommands() {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        CommandLine commandLine = new CommandLine(new QueueSubscriberApp(new QueueSubscriberApp.NoOpQueueOperations()));

        commandLine.usage(new PrintWriter(output, true, StandardCharsets.UTF_8));

        String usage = QueueSubscriberApp.outputText(output);
        assertTrue(usage.contains("queue-subscriber"));
        assertTrue(usage.contains("subscribe"));
        assertTrue(usage.contains("stream"));
        assertTrue(usage.contains("unsubscribe"));
    }

    @Test
    void rootUsageDoesNotAdvertiseVersionOption() {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        CommandLine commandLine = new CommandLine(new QueueSubscriberApp(new QueueSubscriberApp.NoOpQueueOperations()));

        commandLine.usage(new PrintWriter(output, true, StandardCharsets.UTF_8));

        String usage = QueueSubscriberApp.outputText(output);
        assertTrue(usage.contains("-h, --help"));
        assertTrue(!usage.contains("-V, --version"));
    }

    @Test
    void subscribeRejectsIdAndDisplayNameTogether() {
        ByteArrayOutputStream err = new ByteArrayOutputStream();
        CommandLine commandLine = new CommandLine(new QueueSubscriberApp(new QueueSubscriberApp.NoOpQueueOperations()));
        commandLine.setErr(new PrintWriter(err, true, StandardCharsets.UTF_8));

        int exitCode = commandLine.execute("subscribe", "--id", "ocid1.example", "--display-name", "sensor-01");

        assertNotEquals(0, exitCode);
        assertTrue(QueueSubscriberApp.outputText(err).contains("mutually exclusive"));
    }

    @Test
    void subscribePassesArgumentsToQueueService() {
        RecordingQueueOperations queueOperations = new RecordingQueueOperations();
        CommandLine commandLine = new CommandLine(new QueueSubscriberApp(queueOperations));

        int exitCode = commandLine.execute(
                "--config", "samples/java/queues/config.properties",
                "-v",
                "subscribe",
                "--id", "ocid1.example",
                "--content-path", "temperature");

        assertEquals(0, exitCode);
        assertEquals(Path.of("samples/java/queues/config.properties"), queueOperations.configPath);
        assertEquals("ocid1.example", queueOperations.digitalTwinInstanceId);
        assertEquals("temperature", queueOperations.contentPath);
        assertTrue(queueOperations.verbose);
    }

    private static final class RecordingQueueOperations implements QueueOperations {
        private Path configPath;
        private String digitalTwinInstanceId;
        private String contentPath;
        private boolean verbose;

        @Override
        public void subscribe(Path configPath, String digitalTwinInstanceId, String displayName, String contentPath,
                boolean verbose, boolean debug) {
            this.configPath = configPath;
            this.digitalTwinInstanceId = digitalTwinInstanceId;
            this.contentPath = contentPath;
            this.verbose = verbose;
        }

        @Override
        public void stream(Path configPath, boolean verbose, boolean debug) {
        }

        @Override
        public void unsubscribe(Path configPath, boolean verbose, boolean debug) {
        }
    }
}
