package com.smartfarm.models;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class DailyForecastPayload {
    private String date;
    private Double temperature;

    @JsonProperty("rain_chance_percent")
    private Double rainChancePercent;

    private Double humidity;
}