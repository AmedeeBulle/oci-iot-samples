package com.oracle.iot.sample.queues;

import java.sql.SQLException;

import com.oracle.bmc.auth.BasicAuthenticationDetailsProvider;

import oracle.jdbc.AccessToken;
import oracle.jdbc.OracleConnection;
import oracle.jdbc.OracleConnectionBuilder;
import oracle.jdbc.pool.OracleDataSource;

public class DatabaseConnector {

    private final IamDbTokenProvider iamDbTokenProvider;

    public DatabaseConnector() {
        this(new IamDbTokenProvider());
    }

    DatabaseConnector(IamDbTokenProvider iamDbTokenProvider) {
        this.iamDbTokenProvider = iamDbTokenProvider;
    }

    public OracleConnection connect(AppConfig config) throws Exception {
        BasicAuthenticationDetailsProvider provider = OciAuthProviderFactory.create(config);
        AccessToken accessToken = iamDbTokenProvider.createAccessToken(provider, config.dbTokenScope());
        String jdbcUrl = toJdbcUrl(config.dbConnectString());

        OracleDataSource dataSource = new OracleDataSource();
        dataSource.setURL(jdbcUrl);

        OracleConnectionBuilder builder = dataSource.createConnectionBuilder();
        builder.accessToken(accessToken);
        OracleConnection connection = builder.build();
        prepareConnection(connection);
        return connection;
    }

    static String toJdbcUrl(String connectString) {
        return "jdbc:oracle:thin:@" + connectString;
    }

    static void prepareConnection(OracleConnection connection) throws SQLException {
        connection.setAutoCommit(false);
    }
}
