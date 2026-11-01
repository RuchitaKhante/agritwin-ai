package com.smartfarm.models;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import lombok.AllArgsConstructor;

@Data
@AllArgsConstructor
public class WeatherForecastPayload {
    private Double temperature;

    @JsonProperty("rain_chance_percent")
    private Double rainChancePercent;

    @JsonProperty("forecast_time")
    private String forecastTime;
}