package com.smartfarm.models;

import lombok.Data;
import lombok.AllArgsConstructor;

@Data
@AllArgsConstructor
public class SensorReadingPayload {
    private Double moisture;
    private Double temperature;
    private Double humidity;
    private String timestamp;
}