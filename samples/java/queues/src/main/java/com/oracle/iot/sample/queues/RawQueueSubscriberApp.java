package com.oracle.iot.sample.queues;

import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import picocli.CommandLine;
import picocli.CommandLine.ArgGroup;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;
import picocli.CommandLine.Spec;
import picocli.CommandLine.Model.CommandSpec;

@Command(
        name = "raw-queue-subscriber",
        description = "Stream raw ADT messages from the IoT raw_data_in queue."
)
public final class RawQueueSubscriberApp implements java.util.concurrent.Callable<Integer> {

    @Spec
    CommandSpec spec;

    @Option(names = {"-v", "--verbose"}, description = "Enable INFO-level progress output.")
    boolean verbose;

    @Option(names = {"-d", "--debug"}, description = "Print stack traces on errors.")
    boolean debug;

    @Option(names = {"-h", "--help"}, usageHelp = true, description = "Show this help message and exit.")
    boolean helpRequested;

    @Option(names = {"-c", "--config"}, description = "Path to the sample config.properties file.")
    String configPathText;

    @ArgGroup(exclusive = true, multiplicity = "0..1")
    TargetOptions target;

    @Option(names = "--endpoint", description = "Message endpoint filter.")
    String endpoint;

    private final RawQueueOperations rawQueueOperations;

    public RawQueueSubscriberApp() {
        this(new RawQueueService());
    }

    RawQueueSubscriberApp(RawQueueOperations rawQueueOperations) {
        this.rawQueueOperations = rawQueueOperations;
    }

    public static void main(String[] args) {
        int exitCode = new CommandLine(new RawQueueSubscriberApp()).execute(args);
        System.exit(exitCode);
    }

    @Override
    public Integer call() {
        if (helpRequested) {
            spec.commandLine().usage(System.out);
            return 0;
        }

        try {
            rawQueueOperations.stream(
                    resolveConfigPath(),
                    target == null ? null : target.digitalTwinInstanceId,
                    target == null ? null : target.displayName,
                    endpoint,
                    verbose,
                    debug);
            return 0;
        } catch (Exception exception) {
            return handleException(exception);
        }
    }

    Path resolveConfigPath() {
        if (configPathText != null && !configPathText.isBlank()) {
            return Path.of(configPathText);
        }

        Path localPath = Path.of("config.properties");
        if (Files.exists(localPath)) {
            return localPath;
        }

        Path repoPath = Path.of("samples", "java", "queues", "config.properties");
        if (Files.exists(repoPath)) {
            return repoPath;
        }

        return localPath;
    }

    int handleException(Exception exception) {
        PrintWriter err = spec.commandLine().getErr();
        err.println("Error: " + exception.getMessage());
        if (debug) {
            exception.printStackTrace(err);
        }
        err.flush();
        return 1;
    }

    static final class TargetOptions {
        @Option(names = "--id", description = "Digital Twin Instance OCID.")
        String digitalTwinInstanceId;

        @Option(names = "--display-name", description = "Digital Twin Instance display name.")
        String displayName;
    }

    static String outputText(java.io.ByteArrayOutputStream output) {
        return output.toString(StandardCharsets.UTF_8);
    }

    static final class NoOpRawQueueOperations implements RawQueueOperations {
        @Override
        public void stream(Path configPath, String digitalTwinInstanceId, String displayName, String endpoint,
                boolean verbose, boolean debug) {
        }
    }
}
