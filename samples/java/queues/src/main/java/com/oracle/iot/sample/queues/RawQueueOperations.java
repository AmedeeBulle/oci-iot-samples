package com.oracle.iot.sample.queues;

import java.nio.file.Path;

public interface RawQueueOperations {

    void stream(Path configPath, String digitalTwinInstanceId, String displayName, String endpoint,
            boolean verbose, boolean debug) throws Exception;
}
