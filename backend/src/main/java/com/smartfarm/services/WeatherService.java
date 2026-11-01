package com.smartfarm.services;

import com.smartfarm.models.DailyForecastPayload;
import com.smartfarm.models.WeatherForecast;
import com.smartfarm.repositories.WeatherForecastRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

@Service
@SuppressWarnings("unchecked")
public class WeatherService {

    @Autowired
    private WeatherForecastRepository weatherForecastRepository;

    @Value("${weather.latitude}")
    private double latitude;

    @Value("${weather.longitude}")
    private double longitude;

    private final RestTemplate restTemplate = new RestTemplate();

    private static final String BASE = "https://api.open-meteo.com/v1/forecast";

    private String hourlyUrl() {
        return String.format(Locale.US,
            "%s?latitude=%.4f&longitude=%.4f&hourly=temperature_2m,relative_humidity_2m,precipitation,precipitation_probability&timezone=auto",
            BASE, latitude, longitude);
    }

    private String dailyUrl() {
        return String.format(Locale.US,
            "%s?latitude=%.4f&longitude=%.4f&daily=temperature_2m_mean,precipitation_probability_max,relative_humidity_2m_mean&forecast_days=8&timezone=auto",
            BASE, latitude, longitude);
    }

    private static double num(List<?> list, int i) {
        if (list == null || i >= list.size() || list.get(i) == null) return 0.0;
        return ((Number) list.get(i)).doubleValue();
    }

    private static double round1(double v) {
        return Math.round(v * 10.0) / 10.0;
    }

    /** Current-hour forecast, saved to weather_forecast (unchanged behaviour). */
    public WeatherForecast fetchAndSaveForecast() {
        Map<String, Object> response = restTemplate.getForObject(hourlyUrl(), Map.class);
        Map<String, Object> hourly = (Map<String, Object>) response.get("hourly");
        List<String> times = (List<String>) hourly.get("time");
        int idx = Math.min(LocalDateTime.now().getHour(), times.size() - 1);

        WeatherForecast forecast = new WeatherForecast();
        forecast.setTemp(num((List<?>) hourly.get("temperature_2m"), idx));
        forecast.setHumidity(num((List<?>) hourly.get("relative_humidity_2m"), idx));
        forecast.setRainMm(num((List<?>) hourly.get("precipitation"), idx));
        forecast.setRainChancePercent(num((List<?>) hourly.get("precipitation_probability"), idx));
        forecast.setForecastTime(LocalDateTime.parse(times.get(idx)));
        forecast.setFetchedAt(LocalDateTime.now());
        return weatherForecastRepository.save(forecast);
    }

    /** Next 7 days (starting tomorrow). Passed straight to the AI engine, not stored. */
    public List<DailyForecastPayload> fetchDailyForecast() {
        Map<String, Object> response = restTemplate.getForObject(dailyUrl(), Map.class);
        Map<String, Object> daily = (Map<String, Object>) response.get("daily");
        List<String> dates = (List<String>) daily.get("time");
        List<?> temps = (List<?>) daily.get("temperature_2m_mean");
        List<?> rain = (List<?>) daily.get("precipitation_probability_max");
        List<?> hum = (List<?>) daily.get("relative_humidity_2m_mean");

        List<DailyForecastPayload> out = new ArrayList<>();
        for (int i = 1; i < dates.size(); i++) {   // index 0 is today, skip it
            out.add(new DailyForecastPayload(dates.get(i),
                round1(num(temps, i)), round1(num(rain, i)), round1(num(hum, i))));
        }
        return out;
    }

    public WeatherForecast getLatestForecast() {
        return weatherForecastRepository.findTopByOrderByFetchedAtDesc();
    }
}