package com.oracle.iot.sample.queues;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.Proxy;

import org.junit.jupiter.api.Test;

import oracle.jdbc.OracleConnection;

class DatabaseConnectorTest {

    @Test
    void buildsJdbcUrlDirectlyFromConfiguredTcpsConnectString() {
        String connectString =
                "tcps:adb.eu-frankfurt-1.oraclecloud.com:1521/demo_low.adb.oraclecloud.com?retry_count=20&retry_delay=3";

        String jdbcUrl = DatabaseConnector.toJdbcUrl(connectString);

        assertEquals("jdbc:oracle:thin:@" + connectString, jdbcUrl);
    }

    @Test
    void preservesConnectStringWithoutParameters() {
        String connectString =
                "tcps:adb.eu-frankfurt-1.oraclecloud.com:1521/demo_low.adb.oraclecloud.com";

        String jdbcUrl = DatabaseConnector.toJdbcUrl(connectString);

        assertEquals("jdbc:oracle:thin:@" + connectString, jdbcUrl);
    }

    @Test
    void preparesConnectionForExplicitCommits() throws Exception {
        TrackingConnection tracking = new TrackingConnection();
        OracleConnection connection = tracking.proxy();

        DatabaseConnector.prepareConnection(connection);

        assertTrue(tracking.autoCommitDisabled);
    }

    private static final class TrackingConnection implements java.lang.reflect.InvocationHandler {
        private boolean autoCommitDisabled;

        private OracleConnection proxy() {
            return (OracleConnection) Proxy.newProxyInstance(
                    OracleConnection.class.getClassLoader(),
                    new Class<?>[]{OracleConnection.class},
                    this);
        }

        @Override
        public Object invoke(Object proxy, java.lang.reflect.Method method, Object[] args) {
            if ("setAutoCommit".equals(method.getName())) {
                autoCommitDisabled = args != null && args.length == 1 && Boolean.FALSE.equals(args[0]);
                return null;
            }

            Class<?> returnType = method.getReturnType();
            if (returnType.equals(boolean.class)) {
                return false;
            }
            if (returnType.equals(int.class)) {
                return 0;
            }
            if (returnType.equals(long.class)) {
                return 0L;
            }
            return null;
        }
    }
}
