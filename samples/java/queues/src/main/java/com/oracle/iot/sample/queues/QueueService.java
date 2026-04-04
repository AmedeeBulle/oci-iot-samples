package com.oracle.iot.sample.queues;

import java.nio.file.Path;
import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Struct;
import java.sql.Types;
import java.util.Locale;

import oracle.jdbc.OracleConnection;
import oracle.jdbc.aq.AQDequeueOptions;
import oracle.jdbc.aq.AQMessage;
import oracle.sql.json.OracleJsonDatum;
import oracle.sql.json.OracleJsonObject;
import oracle.sql.json.OracleJsonValue;

public class QueueService implements QueueOperations {

    private final DatabaseConnector databaseConnector;

    public QueueService() {
        this(new DatabaseConnector());
    }

    QueueService(DatabaseConnector databaseConnector) {
        this.databaseConnector = databaseConnector;
    }

    @Override
    public void subscribe(Path configPath, String digitalTwinInstanceId, String displayName, String contentPath,
            boolean verbose, boolean debug) throws Exception {
        AppConfig config = AppConfig.load(configPath);
        try (OracleConnection connection = databaseConnector.connect(config)) {
            if (verbose) {
                System.out.println("Connected");
            }

            String rule = SubscriberRuleBuilder.buildRule(
                    digitalTwinInstanceId,
                    displayName,
                    contentPath,
                    name -> resolveDigitalTwinInstanceId(connection, config, name));
            addSubscriber(connection, queueName(config), config.subscriberName(), rule);
            connection.commit();
            System.out.printf("Subscriber %s registered%n", config.subscriberName());
        }
    }

    @Override
    public void stream(Path configPath, boolean verbose, boolean debug) throws Exception {
        AppConfig config = AppConfig.load(configPath);
        try (OracleConnection connection = databaseConnector.connect(config)) {
            if (verbose) {
                System.out.println("Connected");
                System.out.println("Listening for messages");
            }

            AQDequeueOptions dequeueOptions = new AQDequeueOptions();
            dequeueOptions.setDequeueMode(AQDequeueOptions.DequeueMode.REMOVE);
            dequeueOptions.setWait(10);
            dequeueOptions.setNavigation(AQDequeueOptions.NavigationOption.FIRST_MESSAGE);
            dequeueOptions.setConsumerName(config.subscriberName());

            while (!Thread.currentThread().isInterrupted()) {
                AQMessage message = connection.dequeue(queueName(config), dequeueOptions, "JSON");
                if (message == null) {
                    System.out.print(".");
                    System.out.flush();
                    continue;
                }

                printMessage(message.getJSONPayload());
                connection.commit();
            }
        }
    }

    @Override
    public void unsubscribe(Path configPath, boolean verbose, boolean debug) throws Exception {
        AppConfig config = AppConfig.load(configPath);
        try (OracleConnection connection = databaseConnector.connect(config)) {
            if (verbose) {
                System.out.println("Connected");
            }

            removeSubscriber(connection, queueName(config), config.subscriberName());
            connection.commit();
            System.out.printf("Subscriber %s unregistered%n", config.subscriberName());
        }
    }

    private static String queueName(AppConfig config) {
        return (config.iotDomainShortName() + "__iot.normalized_data").toUpperCase(Locale.ROOT);
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

    private static void printMessage(OracleJsonDatum payloadDatum) throws SQLException {
        OracleJsonObject payload = (OracleJsonObject) payloadDatum.toJdbc();

        System.out.println();
        System.out.printf("OCID         : %s%n", payload.getString("digitalTwinInstanceId", ""));
        System.out.printf("Time observed: %s%n", payload.getString("timeObserved", ""));
        System.out.printf("Content path : %s%n", payload.getString("contentPath", ""));
        System.out.printf("Value        : %s%n", jsonValueText(payload.get("value")));
    }

    private static String jsonValueText(OracleJsonValue value) {
        return value == null ? "" : value.toString();
    }
}
