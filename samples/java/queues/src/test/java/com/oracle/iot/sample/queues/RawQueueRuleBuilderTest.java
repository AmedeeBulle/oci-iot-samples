package com.oracle.iot.sample.queues;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class RawQueueRuleBuilderTest {

    @Test
    void returnsNullWhenNoFiltersAreProvided() {
        assertNull(RawQueueRuleBuilder.buildRule(null, null, null, displayName -> null));
    }

    @Test
    void buildsRuleFromInstanceIdAndEndpoint() {
        String rule = RawQueueRuleBuilder.buildRule(
                "ocid1.iotdigitaltwininstance.oc1..example",
                null,
                "zigbee2mqtt/sensor-01",
                displayName -> null);

        assertEquals(
                "tab.user_data.digital_twin_instance_id = 'ocid1.iotdigitaltwininstance.oc1..example' and tab.user_data.endpoint = 'zigbee2mqtt/sensor-01'",
                rule);
    }

    @Test
    void resolvesDisplayNameBeforeBuildingRawRule() {
        String rule = RawQueueRuleBuilder.buildRule(
                null,
                "sensor-01",
                "topic/a",
                displayName -> "ocid1.iotdigitaltwininstance.oc1..resolved");

        assertEquals(
                "tab.user_data.digital_twin_instance_id = 'ocid1.iotdigitaltwininstance.oc1..resolved' and tab.user_data.endpoint = 'topic/a'",
                rule);
    }

    @Test
    void failsWhenDisplayNameCannotBeResolved() {
        IllegalArgumentException error = assertThrows(IllegalArgumentException.class,
                () -> RawQueueRuleBuilder.buildRule(null, "missing-device", null, displayName -> null));

        assertEquals("No such display name: missing-device", error.getMessage());
    }
}
