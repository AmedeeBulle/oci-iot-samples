package com.oracle.iot.sample.queues;

import java.security.GeneralSecurityException;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.util.Base64;

import com.oracle.bmc.Region;
import com.oracle.bmc.auth.BasicAuthenticationDetailsProvider;
import com.oracle.bmc.auth.RegionProvider;
import com.oracle.bmc.identitydataplane.DataplaneClient;
import com.oracle.bmc.identitydataplane.model.GenerateScopedAccessTokenDetails;
import com.oracle.bmc.identitydataplane.requests.GenerateScopedAccessTokenRequest;

import oracle.jdbc.AccessToken;

public class IamDbTokenProvider {

    public AccessToken createAccessToken(BasicAuthenticationDetailsProvider provider, String scope) {
        if (!(provider instanceof RegionProvider regionProvider)) {
            throw new IllegalArgumentException("OCI auth provider must implement RegionProvider");
        }

        Region region = regionProvider.getRegion();
        if (region == null) {
            throw new IllegalArgumentException("OCI auth provider does not expose a region");
        }

        KeyPair keyPair = generateKeyPair();
        String publicKeyPem = toPublicKeyPem(keyPair);

        try (DataplaneClient dataplaneClient = DataplaneClient.builder().build(provider)) {
            dataplaneClient.setRegion(region);
            GenerateScopedAccessTokenRequest request = GenerateScopedAccessTokenRequest.builder()
                    .generateScopedAccessTokenDetails(
                            GenerateScopedAccessTokenDetails.builder()
                                    .scope(scope)
                                    .publicKey(publicKeyPem)
                                    .build())
                    .build();

            String token = dataplaneClient.generateScopedAccessToken(request).getSecurityToken().getToken();
            return AccessToken.createJsonWebToken(token.toCharArray(), keyPair.getPrivate());
        }
    }

    private KeyPair generateKeyPair() {
        try {
            KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
            generator.initialize(2048);
            return generator.generateKeyPair();
        } catch (GeneralSecurityException exception) {
            throw new IllegalStateException("Failed to generate temporary RSA key pair", exception);
        }
    }

    private String toPublicKeyPem(KeyPair keyPair) {
        return toPem("PUBLIC KEY", keyPair.getPublic().getEncoded());
    }

    static String toPem(String label, byte[] encoded) {
        Base64.Encoder encoder = Base64.getMimeEncoder(64, new byte[]{'\n'});
        return "-----BEGIN " + label + "-----\n"
                + encoder.encodeToString(encoded)
                + "\n-----END " + label + "-----";
    }
}
