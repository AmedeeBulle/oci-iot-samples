package com.oracle.iot.sample.queues;

import java.io.IOException;

import com.oracle.bmc.auth.BasicAuthenticationDetailsProvider;
import com.oracle.bmc.auth.ConfigFileAuthenticationDetailsProvider;
import com.oracle.bmc.auth.InstancePrincipalsAuthenticationDetailsProvider;
import com.oracle.bmc.auth.SessionTokenAuthenticationDetailsProvider;

public final class OciAuthProviderFactory {

    private OciAuthProviderFactory() {
    }

    public static BasicAuthenticationDetailsProvider create(AppConfig config) throws IOException {
        return switch (config.ociAuthType()) {
            case "ConfigFileAuthentication" -> createConfigFileProvider(config);
            case "SecurityToken" -> createSecurityTokenProvider(config);
            case "InstancePrincipal" -> InstancePrincipalsAuthenticationDetailsProvider.builder().build();
            default -> throw new IllegalArgumentException("Unsupported OCI auth type: " + config.ociAuthType());
        };
    }

    private static BasicAuthenticationDetailsProvider createConfigFileProvider(AppConfig config) throws IOException {
        return new ConfigFileAuthenticationDetailsProvider(config.ociConfigFile(), config.ociProfile());
    }

    private static BasicAuthenticationDetailsProvider createSecurityTokenProvider(AppConfig config) throws IOException {
        return new SessionTokenAuthenticationDetailsProvider(config.ociConfigFile(), config.ociProfile());
    }
}
