package com.oracle.iot.sample.queues;

import java.util.ArrayList;
import java.util.List;

public final class SubscriberRuleBuilder {

    @FunctionalInterface
    public interface DisplayNameResolver {
        String resolve(String displayName) throws Exception;
    }

    private SubscriberRuleBuilder() {
    }

    public static String buildRule(
            String digitalTwinInstanceId,
            String displayName,
            String contentPath,
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
            conditions.add("tab.user_data.\"digitalTwinInstanceId\" = " + quoteLiteral(resolvedInstanceId));
        }
        if (contentPath != null && !contentPath.isBlank()) {
            conditions.add("tab.user_data.\"contentPath\" = " + quoteLiteral(contentPath));
        }

        return conditions.isEmpty() ? null : String.join(" and ", conditions);
    }

    private static String quoteLiteral(String value) {
        return "'" + value.replace("'", "''") + "'";
    }
}
