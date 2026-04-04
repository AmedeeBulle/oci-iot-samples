package com.oracle.iot.sample.queues;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Objects;
import java.util.Properties;

public record AppConfig(
        String dbConnectString,
        String dbTokenScope,
        String iotDomainShortName,
        String ociAuthType,
        String ociProfile,
        String ociConfigFile,
        String subscriberName) {

    public static AppConfig load(Path path) throws IOException {
        Properties properties = new Properties();
        try (InputStream inputStream = Files.newInputStream(path)) {
            properties.load(inputStream);
        }

        return new AppConfig(
                required(properties, "db.connect.string"),
                required(properties, "db.token.scope"),
                required(properties, "iot.domain.short.name"),
                required(properties, "oci.auth.type"),
                properties.getProperty("oci.profile", "DEFAULT").trim(),
                defaulted(properties, "oci.config.file", defaultOciConfigPath()),
                required(properties, "subscriber.name"));
    }

    private static String defaultOciConfigPath() {
        return Path.of(System.getProperty("user.home"), ".oci", "config").toString();
    }

    private static String required(Properties properties, String key) {
        String value = properties.getProperty(key);
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Missing required property: " + key);
        }
        return value.trim();
    }

    private static String defaulted(Properties properties, String key, String defaultValue) {
        String value = properties.getProperty(key);
        if (value == null || value.isBlank()) {
            return defaultValue;
        }
        return value.trim();
    }

    public AppConfig {
        Objects.requireNonNull(dbConnectString, "dbConnectString");
        Objects.requireNonNull(dbTokenScope, "dbTokenScope");
        Objects.requireNonNull(iotDomainShortName, "iotDomainShortName");
        Objects.requireNonNull(ociAuthType, "ociAuthType");
        Objects.requireNonNull(ociProfile, "ociProfile");
        Objects.requireNonNull(ociConfigFile, "ociConfigFile");
        Objects.requireNonNull(subscriberName, "subscriberName");
    }
}
