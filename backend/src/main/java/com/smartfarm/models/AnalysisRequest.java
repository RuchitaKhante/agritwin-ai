package com.smartfarm.models;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import java.util.List;

@Data
@AllArgsConstructor
public class AnalysisRequest {

    @JsonProperty("sensor_history")
    private List<SensorReadingPayload> sensorHistory;

    @JsonProperty("weather_forecast")
    private WeatherForecastPayload weatherForecast;

    @JsonProperty("daily_forecast")
    private List<DailyForecastPayload> dailyForecast;

    @JsonProperty("session_id")
    private String sessionId;
}