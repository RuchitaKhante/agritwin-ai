package com.smartfarm.models;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import lombok.AllArgsConstructor;

@Data
@AllArgsConstructor
public class ChatRequestPayload {

    private String message;

    @JsonProperty("session_id")
    private String sessionId;
}