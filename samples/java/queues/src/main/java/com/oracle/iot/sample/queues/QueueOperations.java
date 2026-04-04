package com.oracle.iot.sample.queues;

import java.nio.file.Path;

public interface QueueOperations {

    void subscribe(Path configPath, String digitalTwinInstanceId, String displayName, String contentPath,
            boolean verbose, boolean debug) throws Exception;

    void stream(Path configPath, boolean verbose, boolean debug) throws Exception;

    void unsubscribe(Path configPath, boolean verbose, boolean debug) throws Exception;
}
