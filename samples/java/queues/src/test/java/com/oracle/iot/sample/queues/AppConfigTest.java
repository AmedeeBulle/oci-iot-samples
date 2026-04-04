package com.oracle.iot.sample.queues;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class AppConfigTest {

    @TempDir
    Path tempDir;

    @Test
    void loadsRequiredPropertiesAndDefaultProfile() throws IOException {
        Path configPath = tempDir.resolve("config.properties");
        Files.writeString(configPath, String.join("\n",
                "db.connect.string=tcps:adb.example.oraclecloud.com:1521/demo_low.adb.oraclecloud.com?retry_count=20&retry_delay=3",
                "db.token.scope=urn:oracle:db::id::ocid1.compartment.oc1..example",
                "iot.domain.short.name=demo123",
                "oci.auth.type=InstancePrincipal",
                "subscriber.name=test_subscriber"));

        AppConfig config = AppConfig.load(configPath);

        assertEquals("tcps:adb.example.oraclecloud.com:1521/demo_low.adb.oraclecloud.com?retry_count=20&retry_delay=3",
                config.dbConnectString());
        assertEquals("urn:oracle:db::id::ocid1.compartment.oc1..example", config.dbTokenScope());
        assertEquals("demo123", config.iotDomainShortName());
        assertEquals("InstancePrincipal", config.ociAuthType());
        assertEquals("DEFAULT", config.ociProfile());
        assertEquals(Path.of(System.getProperty("user.home"), ".oci", "config").toString(), config.ociConfigFile());
        assertEquals("test_subscriber", config.subscriberName());
    }

    @Test
    void failsWhenRequiredPropertyIsMissing() throws IOException {
        Path configPath = tempDir.resolve("config.properties");
        Files.writeString(configPath, "db.token.scope=urn:oracle:db::id::ocid1.compartment.oc1..example\n");

        IllegalArgumentException error = assertThrows(IllegalArgumentException.class, () -> AppConfig.load(configPath));

        assertEquals("Missing required property: db.connect.string", error.getMessage());
    }
}
