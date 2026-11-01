package com.smartfarm.models;

import jakarta.persistence.*;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;
import java.time.LocalDateTime;

@Entity
@Table(name = "weather_forecast")
@Data
@NoArgsConstructor
@AllArgsConstructor
public class WeatherForecast {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "rain_mm")
    private Double rainMm;

    private Double temp;

    private Double humidity;

    @Column(name = "forecast_time")
    private LocalDateTime forecastTime;

    @Column(name = "fetched_at")
    private LocalDateTime fetchedAt;
    
    @Column(name = "rain_chance_percent")
    private Double rainChancePercent;
}