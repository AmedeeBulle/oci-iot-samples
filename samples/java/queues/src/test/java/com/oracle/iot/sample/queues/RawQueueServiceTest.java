package com.oracle.iot.sample.queues;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;

import javax.sql.rowset.serial.SerialBlob;

import org.junit.jupiter.api.Test;

class RawQueueServiceTest {

    @Test
    void buildsRawQueueNameFromDomainShortName() {
        AppConfig config = new AppConfig(
                "tcps:adb.example.oraclecloud.com:1521/demo_low.adb.oraclecloud.com",
                "urn:oracle:db::id::ocid1.compartment.oc1..example",
                "demo123",
                "ConfigFileAuthentication",
                "DEFAULT",
                "",
                "subscriber");

        assertEquals("DEMO123__IOT.RAW_DATA_IN", RawQueueService.queueName(config));
    }

    @Test
    void generatesUniqueEphemeralSubscriberNames() {
        String first = RawQueueService.generateSubscriberName();
        String second = RawQueueService.generateSubscriberName();

        assertTrue(first.startsWith("aq_sub_"));
        assertTrue(second.startsWith("aq_sub_"));
        assertNotEquals(first, second);
    }

    @Test
    void decodesBlobContentAsUtf8Text() throws Exception {
        SerialBlob blob = new SerialBlob("{\"temperature\":21.3}".getBytes(StandardCharsets.UTF_8));

        assertEquals("{\"temperature\":21.3}", RawQueueService.decodeContent(blob));
    }

    @Test
    void mapsRawAdtAttributesInDocumentedOrder() throws Exception {
        Object[] attributes = {
                "ocid1.iotdigitaltwininstance.oc1..example",
                "zigbee2mqtt/sensor-01",
                new SerialBlob("{\"temperature\":21.3}".getBytes(StandardCharsets.UTF_8)),
                "application/json",
                "2026-04-03T12:34:56Z"
        };

        RawQueueService.RawMessageData messageData = RawQueueService.mapMessage(attributes);

        assertEquals("ocid1.iotdigitaltwininstance.oc1..example", messageData.digitalTwinInstanceId());
        assertEquals("2026-04-03T12:34:56Z", messageData.timeReceived());
        assertEquals("zigbee2mqtt/sensor-01", messageData.endpoint());
        assertEquals("{\"temperature\":21.3}", messageData.content());
    }

    @Test
    void formatsBinaryContentSafely() throws Exception {
        byte[] binary = {(byte) 0x00, (byte) 0x01, (byte) 0xff, (byte) 0xa5};

        assertEquals("<binary 4 bytes>", RawQueueService.decodeContent(binary));
    }
}
