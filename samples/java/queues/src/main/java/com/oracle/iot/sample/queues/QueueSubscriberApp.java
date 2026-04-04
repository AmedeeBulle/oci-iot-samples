package com.oracle.iot.sample.queues;

import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import picocli.CommandLine;
import picocli.CommandLine.ArgGroup;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;
import picocli.CommandLine.ParentCommand;
import picocli.CommandLine.Spec;
import picocli.CommandLine.Model.CommandSpec;

@Command(
        name = "queue-subscriber",
        description = "Manage and consume an IoT normalized JSON queue subscriber.",
        subcommands = {
                QueueSubscriberApp.SubscribeCommand.class,
                QueueSubscriberApp.StreamCommand.class,
                QueueSubscriberApp.UnsubscribeCommand.class
        }
)
public final class QueueSubscriberApp implements Runnable {

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

    private final QueueOperations queueOperations;

    public QueueSubscriberApp() {
        this(new QueueService());
    }

    QueueSubscriberApp(QueueOperations queueOperations) {
        this.queueOperations = queueOperations;
    }

    public static void main(String[] args) {
        int exitCode = new CommandLine(new QueueSubscriberApp()).execute(args);
        System.exit(exitCode);
    }

    @Override
    public void run() {
        spec.commandLine().usage(System.out);
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

    @Command(name = "subscribe", description = "Create a durable subscriber.")
    static final class SubscribeCommand implements java.util.concurrent.Callable<Integer> {
        @ParentCommand
        QueueSubscriberApp parent;

        @ArgGroup(exclusive = true, multiplicity = "0..1")
        TargetOptions target;

        @Option(names = "--content-path", description = "Normalized content path filter.")
        String contentPath;

        @Override
        public Integer call() {
            try {
                parent.queueOperations.subscribe(
                        parent.resolveConfigPath(),
                        target == null ? null : target.digitalTwinInstanceId,
                        target == null ? null : target.displayName,
                        contentPath,
                        parent.verbose,
                        parent.debug);
                return 0;
            } catch (Exception exception) {
                return parent.handleException(exception);
            }
        }
    }

    @Command(name = "stream", description = "Consume messages from a durable subscriber.")
    static final class StreamCommand implements java.util.concurrent.Callable<Integer> {
        @ParentCommand
        QueueSubscriberApp parent;

        @Override
        public Integer call() {
            try {
                parent.queueOperations.stream(parent.resolveConfigPath(), parent.verbose, parent.debug);
                return 0;
            } catch (Exception exception) {
                return parent.handleException(exception);
            }
        }
    }

    @Command(name = "unsubscribe", description = "Delete a durable subscriber.")
    static final class UnsubscribeCommand implements java.util.concurrent.Callable<Integer> {
        @ParentCommand
        QueueSubscriberApp parent;

        @Override
        public Integer call() {
            try {
                parent.queueOperations.unsubscribe(parent.resolveConfigPath(), parent.verbose, parent.debug);
                return 0;
            } catch (Exception exception) {
                return parent.handleException(exception);
            }
        }
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

    static final class NoOpQueueOperations implements QueueOperations {
        @Override
        public void subscribe(Path configPath, String digitalTwinInstanceId, String displayName, String contentPath,
                boolean verbose, boolean debug) {
        }

        @Override
        public void stream(Path configPath, boolean verbose, boolean debug) {
        }

        @Override
        public void unsubscribe(Path configPath, boolean verbose, boolean debug) {
        }
    }
}
