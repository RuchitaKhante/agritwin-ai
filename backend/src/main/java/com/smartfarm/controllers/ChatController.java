package com.smartfarm.controllers;

import com.smartfarm.exceptions.ExternalServiceException;
import com.smartfarm.models.ChatRequestPayload;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

@RestController
@RequestMapping("/api/chat")
public class ChatController {

    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${fastapi.base-url}")
    private String fastApiBaseUrl;

    @PostMapping
    public ResponseEntity<Map> sendMessage(@RequestBody ChatRequestPayload request) {

        ChatRequestPayload payload = new ChatRequestPayload(
            request.getMessage(),
            request.getSessionId() != null ? request.getSessionId() : "default"
        );

        Map response;
        try {
            String chatUrl = fastApiBaseUrl + "/chat";
            response = restTemplate.postForObject(chatUrl, payload, Map.class);
        } catch (Exception e) {
            throw new ExternalServiceException("Chat assistant is unavailable: " + e.getMessage());
        }

        return ResponseEntity.ok(response);
    }
}