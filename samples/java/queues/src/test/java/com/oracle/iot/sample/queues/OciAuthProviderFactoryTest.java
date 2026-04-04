package com.oracle.iot.sample.queues;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.nio.file.Path;

import org.junit.jupiter.api.Test;

class OciAuthProviderFactoryTest {

    @Test
    void rejectsUnsupportedAuthenticationType() {
        AppConfig config = new AppConfig(
                "tcps:adb.example.oraclecloud.com:1521/demo_low.adb.oraclecloud.com",
                "urn:oracle:db::id::ocid1.compartment.oc1..example",
                "demo123",
                "UnknownAuth",
                "DEFAULT",
                Path.of("/tmp/oci-config").toString(),
                "subscriber");

        IllegalArgumentException error = assertThrows(IllegalArgumentException.class,
                () -> OciAuthProviderFactory.create(config));

        assertEquals("Unsupported OCI auth type: UnknownAuth", error.getMessage());
    }
}
