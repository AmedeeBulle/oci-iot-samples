package com.oracle.iot.sample.queues;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class SubscriberRuleBuilderTest {

    @Test
    void returnsNullWhenNoFiltersAreProvided() {
        assertNull(SubscriberRuleBuilder.buildRule(null, null, null, displayName -> null));
    }

    @Test
    void buildsRuleFromInstanceIdAndContentPath() {
        String rule = SubscriberRuleBuilder.buildRule(
                "ocid1.iotdigitaltwininstance.oc1..example",
                null,
                "temperature",
                displayName -> null);

        assertEquals(
                "tab.user_data.\"digitalTwinInstanceId\" = 'ocid1.iotdigitaltwininstance.oc1..example' and tab.user_data.\"contentPath\" = 'temperature'",
                rule);
    }

    @Test
    void resolvesDisplayNameBeforeBuildingRule() {
        String rule = SubscriberRuleBuilder.buildRule(
                null,
                "sensor-01",
                "humidity",
                displayName -> "ocid1.iotdigitaltwininstance.oc1..resolved");

        assertEquals(
                "tab.user_data.\"digitalTwinInstanceId\" = 'ocid1.iotdigitaltwininstance.oc1..resolved' and tab.user_data.\"contentPath\" = 'humidity'",
                rule);
    }

    @Test
    void failsWhenDisplayNameCannotBeResolved() {
        IllegalArgumentException error = assertThrows(IllegalArgumentException.class,
                () -> SubscriberRuleBuilder.buildRule(null, "missing-device", null, displayName -> null));

        assertEquals("No such display name: missing-device", error.getMessage());
    }

    @Test
    void escapesSingleQuotesInValues() {
        String rule = SubscriberRuleBuilder.buildRule(
                "ocid'example",
                null,
                "temp'path",
                displayName -> null);

        assertEquals(
                "tab.user_data.\"digitalTwinInstanceId\" = 'ocid''example' and tab.user_data.\"contentPath\" = 'temp''path'",
                rule);
    }
}
