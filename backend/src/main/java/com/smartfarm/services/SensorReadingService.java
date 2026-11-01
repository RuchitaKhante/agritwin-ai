package com.smartfarm.services;

import com.smartfarm.models.DailyAverage;
import com.smartfarm.models.DailyReading;
import com.smartfarm.models.SensorReading;
import com.smartfarm.repositories.SensorReadingRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

@Service
public class SensorReadingService {

    @Autowired
    private SensorReadingRepository sensorReadingRepository;

    public SensorReading saveReading(SensorReading reading) {
        // If ESP32 doesn't send a timestamp, we set it ourselves on arrival
        if (reading.getReadingTime() == null) {
            reading.setReadingTime(LocalDateTime.now());
        }
        return sensorReadingRepository.save(reading);
    }

    public SensorReading getLatestReading() {
        return sensorReadingRepository.findTopByOrderByReadingTimeDesc();
    }

    public List<SensorReading> getRecentReadings() {
        return sensorReadingRepository.findTop5ByOrderByReadingTimeDesc();
    }

    public List<SensorReading> getMoistureHistory() {
        List<SensorReading> readings = sensorReadingRepository.findTop15ByOrderByReadingTimeDesc();

        // DB returns newest-first; charts read left-to-right chronologically, so reverse it
        Collections.reverse(readings);
        return readings;
    }

    // NEW: last 60 readings, oldest first, for the live sensor graph
    public List<SensorReading> getChartReadings() {
        List<SensorReading> readings = new ArrayList<>(
                sensorReadingRepository.findTop60ByOrderByReadingTimeDesc());
        Collections.reverse(readings);
        return readings;
    }

    public List<DailyReading> getDailyReadings() {
        List<DailyAverage> rows = new ArrayList<>(sensorReadingRepository.findRecentDailyAverages());
        Collections.reverse(rows);   // oldest -> newest, as the model expects
        return rows.stream()
            .map(r -> new DailyReading(r.getReadingDay(), round1(r.getMoisture()),
                    round1(r.getTemperature()), round1(r.getHumidity())))
            .collect(Collectors.toList());
    }

    private double round1(Double v) {
        return v == null ? 0.0 : Math.round(v * 10.0) / 10.0;
    }
}