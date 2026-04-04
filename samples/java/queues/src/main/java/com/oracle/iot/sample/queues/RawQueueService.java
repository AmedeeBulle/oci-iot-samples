package com.oracle.iot.sample.queues;

import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.file.Path;
import java.sql.Blob;
import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Struct;
import java.sql.Types;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

import oracle.jdbc.OracleConnection;
import oracle.jdbc.aq.AQDequeueOptions;
import oracle.jdbc.aq.AQMessage;

public class RawQueueService implements RawQueueOperations {

    private final DatabaseConnector databaseConnector;

    public RawQueueService() {
        this(new DatabaseConnector());
    }

    RawQueueService(DatabaseConnector databaseConnector) {
        this.databaseConnector = databaseConnector;
    }

    @Override
    public void stream(Path configPath, String digitalTwinInstanceId, String displayName, String endpoint,
            boolean verbose, boolean debug) throws Exception {
        AppConfig config = AppConfig.load(configPath);
        try (OracleConnection connection = databaseConnector.connect(config)) {
            if (verbose) {
                System.out.println("Connected");
            }

            String subscriberName = generateSubscriberName();
            String rule = RawQueueRuleBuilder.buildRule(
                    digitalTwinInstanceId,
                    displayName,
                    endpoint,
                    name -> resolveDigitalTwinInstanceId(connection, config, name));

            addSubscriber(connection, queueName(config), subscriberName, rule);
            connection.commit();
            if (verbose) {
                System.out.printf("Subscriber %s registered%n", subscriberName);
                System.out.println("Listening for messages");
            }

            AtomicBoolean unsubscribed = new AtomicBoolean(false);
            Thread shutdownHook = createShutdownHook(connection, config, subscriberName, unsubscribed, verbose);
            Runtime.getRuntime().addShutdownHook(shutdownHook);
            try {
                streamMessages(connection, config, subscriberName);
            } finally {
                removeShutdownHookQuietly(shutdownHook);
                removeSubscriberIfNeeded(connection, config, subscriberName, unsubscribed, verbose);
            }
        }
    }

    private static Thread createShutdownHook(
            OracleConnection connection,
            AppConfig config,
            String subscriberName,
            AtomicBoolean unsubscribed,
            boolean verbose) {
        return new Thread(() -> {
            try {
                removeSubscriberIfNeeded(connection, config, subscriberName, unsubscribed, verbose);
            } catch (Exception ignored) {
                // Best-effort cleanup only.
            }
        }, "raw-queue-cleanup");
    }

    private static void removeShutdownHookQuietly(Thread shutdownHook) {
        try {
            Runtime.getRuntime().removeShutdownHook(shutdownHook);
        } catch (IllegalStateException ignored) {
            // JVM is already shutting down.
        }
    }

    private static void removeSubscriberIfNeeded(
            OracleConnection connection,
            AppConfig config,
            String subscriberName,
            AtomicBoolean unsubscribed,
            boolean verbose) throws SQLException {
        if (unsubscribed.compareAndSet(false, true)) {
            removeSubscriber(connection, queueName(config), subscriberName);
            connection.commit();
            if (verbose) {
                System.out.printf("Subscriber %s unregistered%n", subscriberName);
            }
        }
    }

    private static void streamMessages(OracleConnection connection, AppConfig config, String subscriberName)
            throws Exception {
        AQDequeueOptions dequeueOptions = new AQDequeueOptions();
        dequeueOptions.setDequeueMode(AQDequeueOptions.DequeueMode.REMOVE);
        dequeueOptions.setWait(10);
        dequeueOptions.setNavigation(AQDequeueOptions.NavigationOption.NEXT_MESSAGE);
        dequeueOptions.setConsumerName(subscriberName);

        while (true) {
            AQMessage message = connection.dequeue(queueName(config), dequeueOptions, queuePayloadTypeName(config));
            if (message == null) {
                System.out.print(".");
                System.out.flush();
                continue;
            }

            printMessage(message.getStructPayload(connection));
            connection.commit();
        }
    }

    static String queueName(AppConfig config) {
        return (config.iotDomainShortName() + "__iot.raw_data_in").toUpperCase(Locale.ROOT);
    }

    static String queuePayloadTypeName(AppConfig config) {
        return queueName(config) + "_TYPE";
    }

    static String generateSubscriberName() {
        return "aq_sub_" + UUID.randomUUID().toString().replace('-', '_');
    }

    private static void addSubscriber(OracleConnection connection, String queueName, String subscriberName, String rule)
            throws SQLException {
        try (CallableStatement statement = connection.prepareCall(
                "begin dbms_aqadm.add_subscriber("
                        + "queue_name => ?, "
                        + "subscriber => ?, "
                        + "rule => ?, "
                        + "transformation => null, "
                        + "queue_to_queue => false, "
                        + "delivery_mode => dbms_aqadm.persistent_or_buffered); end;")) {
            statement.setString(1, queueName);
            statement.setObject(2, createSubscriberStruct(connection, subscriberName));
            if (rule == null) {
                statement.setNull(3, Types.VARCHAR);
            } else {
                statement.setString(3, rule);
            }
            statement.execute();
        }
    }

    private static void removeSubscriber(OracleConnection connection, String queueName, String subscriberName)
            throws SQLException {
        try (CallableStatement statement = connection.prepareCall(
                "begin dbms_aqadm.remove_subscriber(queue_name => ?, subscriber => ?); end;")) {
            statement.setString(1, queueName);
            statement.setObject(2, createSubscriberStruct(connection, subscriberName));
            statement.execute();
        }
    }

    private static Struct createSubscriberStruct(OracleConnection connection, String subscriberName) throws SQLException {
        return connection.createStruct("SYS.AQ$_AGENT", new Object[]{subscriberName, null, 0});
    }

    private static String resolveDigitalTwinInstanceId(OracleConnection connection, AppConfig config, String displayName)
            throws SQLException {
        String sql = """
                select dti.data.id
                from %s__iot.digital_twin_instances dti
                where dti.data."displayName" = ?
                  and dti.data."lifecycleState" = 'ACTIVE'
                order by dti.data."timeUpdated" desc
                fetch first 1 row only
                """.formatted(config.iotDomainShortName());
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, displayName);
            try (ResultSet resultSet = statement.executeQuery()) {
                if (resultSet.next()) {
                    return resultSet.getString(1);
                }
                return null;
            }
        }
    }

    private static void printMessage(Struct payload) throws Exception {
        RawMessageData message = mapMessage(payload.getAttributes());

        System.out.println();
        System.out.printf("OCID         : %s%n", message.digitalTwinInstanceId());
        System.out.printf("Time received: %s%n", message.timeReceived());
        System.out.printf("Endpoint     : %s%n", message.endpoint());
        System.out.printf("Content      : %s%n", message.content());
    }

    static RawMessageData mapMessage(Object[] attributes) throws Exception {
        // JDBC exposes the raw_data_in ADT payload as a Struct, so the values arrive
        // in the database type's declared attribute order:
        // DIGITAL_TWIN_INSTANCE_ID, ENDPOINT, CONTENT, CONTENT_TYPE, TIME_RECEIVED.
        // https://docs.oracle.com/en-us/iaas/Content/internet-of-things/iot-domain-database-schema.htm#queues__raw-data-queues
        return new RawMessageData(
                stringValue(attributes, 0),
                stringValue(attributes, 4),
                stringValue(attributes, 1),
                decodeContent(attributes[2]));
    }

    static String decodeContent(Object content) throws Exception {
        if (content == null) {
            return "";
        }
        if (content instanceof Blob blob) {
            return decodeContent(blob);
        }
        if (content instanceof byte[] bytes) {
            return decodeBytes(bytes);
        }
        return content.toString();
    }

    static String decodeContent(Blob blob) throws Exception {
        byte[] bytes = blob.getBytes(1, (int) blob.length());
        return decodeBytes(bytes);
    }

    private static String decodeBytes(byte[] bytes) {
        try {
            CharBuffer decoded = StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes));
            String text = decoded.toString();
            return isPrintableText(text) ? text : "<binary " + bytes.length + " bytes>";
        } catch (CharacterCodingException exception) {
            return "<binary " + bytes.length + " bytes>";
        }
    }

    private static boolean isPrintableText(String text) {
        for (int i = 0; i < text.length(); i++) {
            char current = text.charAt(i);
            if (Character.isISOControl(current) && current != '\n' && current != '\r' && current != '\t') {
                return false;
            }
        }
        return true;
    }

    private static String stringValue(Object[] attributes, int index) {
        Object value = index < attributes.length ? attributes[index] : null;
        return value == null ? "" : value.toString();
    }

    record RawMessageData(
            String digitalTwinInstanceId,
            String timeReceived,
            String endpoint,
            String content) {
    }
}
