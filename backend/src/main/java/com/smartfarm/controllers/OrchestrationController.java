package com.smartfarm.controllers;

import com.smartfarm.exceptions.ExternalServiceException;
import com.smartfarm.models.*;
import com.smartfarm.services.SensorReadingService;
import com.smartfarm.services.WeatherService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/api/advisory")
public class OrchestrationController {

    @Autowired
    private SensorReadingService sensorReadingService;

    @Autowired
    private WeatherService weatherService;

    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${fastapi.base-url}")
    private String fastApiBaseUrl;

    private static double clamp(double v) {
        return Math.max(0, Math.min(100, v));
    }

    @GetMapping
    public ResponseEntity<Map> getAdvisory() {

        // A: daily averages of real sensor readings (the model works in 24-hour steps)
        List<DailyReading> days = sensorReadingService.getDailyReadings();
        if (days.isEmpty()) {
            throw new ExternalServiceException("No sensor data available yet. Make sure the ESP32 has sent at least one reading.");
        }
        List<SensorReadingPayload> history = days.stream()
            .map(d -> new SensorReadingPayload(clamp(d.moisture()), d.temperature(),
                    clamp(d.humidity()), d.date() + "T12:00:00"))
            .collect(Collectors.toList());

        // B: weather - current hour + next 7 days
        WeatherForecast weather;
        List<DailyForecastPayload> dailyForecast;
        try {
            weather = weatherService.fetchAndSaveForecast();
            dailyForecast = weatherService.fetchDailyForecast();
        } catch (Exception e) {
            throw new ExternalServiceException("Failed to fetch weather data: " + e.getMessage());
        }
        WeatherForecastPayload weatherPayload = new WeatherForecastPayload(
            weather.getTemp(), weather.getRainChancePercent(), weather.getForecastTime().toString());

        // C: one request in the shape the AI engine expects
        AnalysisRequest request = new AnalysisRequest(history, weatherPayload, dailyForecast, "default");

        // D: call FastAPI and pass its response straight through
        Map response;
        try {
            response = restTemplate.postForObject(fastApiBaseUrl + "/analyze", request, Map.class);
        } catch (Exception e) {
            throw new ExternalServiceException("FastAPI analysis service is unavailable: " + e.getMessage());
        }
        return ResponseEntity.ok(response);
    }
}