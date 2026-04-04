package com.oracle.iot.sample.queues;

import java.util.ArrayList;
import java.util.List;

public final class RawQueueRuleBuilder {

    @FunctionalInterface
    public interface DisplayNameResolver {
        String resolve(String displayName) throws Exception;
    }

    private RawQueueRuleBuilder() {
    }

    public static String buildRule(
            String digitalTwinInstanceId,
            String displayName,
            String endpoint,
            DisplayNameResolver resolver) {
        String resolvedInstanceId = digitalTwinInstanceId;
        if (displayName != null && !displayName.isBlank()) {
            try {
                resolvedInstanceId = resolver.resolve(displayName);
            } catch (RuntimeException exception) {
                throw exception;
            } catch (Exception exception) {
                throw new IllegalStateException("Failed to resolve display name: " + displayName, exception);
            }
            if (resolvedInstanceId == null || resolvedInstanceId.isBlank()) {
                throw new IllegalArgumentException("No such display name: " + displayName);
            }
        }

        List<String> conditions = new ArrayList<>();
        if (resolvedInstanceId != null && !resolvedInstanceId.isBlank()) {
            conditions.add("tab.user_data.digital_twin_instance_id = " + quoteLiteral(resolvedInstanceId));
        }
        if (endpoint != null && !endpoint.isBlank()) {
            conditions.add("tab.user_data.endpoint = " + quoteLiteral(endpoint));
        }

        return conditions.isEmpty() ? null : String.join(" and ", conditions);
    }

    private static String quoteLiteral(String value) {
        return "'" + value.replace("'", "''") + "'";
    }
}
