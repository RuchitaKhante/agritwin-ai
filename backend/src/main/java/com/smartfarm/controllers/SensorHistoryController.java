package com.smartfarm.controllers;

import com.smartfarm.models.DailyReading;
import com.smartfarm.models.SensorReading;
import com.smartfarm.services.SensorReadingService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/sensor-data")
public class SensorHistoryController {

    @Autowired
    private SensorReadingService sensorReadingService;

    @GetMapping("/history")
    public List<SensorReading> getHistory() {
        return sensorReadingService.getMoistureHistory();
    }

    @GetMapping("/latest")
    public SensorReading getLatest() {
        return sensorReadingService.getLatestReading();
    }

    @GetMapping("/daily")
    public List<DailyReading> getDaily() {
        return sensorReadingService.getDailyReadings();
    }

    // NEW: last 60 readings (oldest first) for the live sensor graph
    @GetMapping("/recent")
    public List<SensorReading> getRecent() {
        return sensorReadingService.getChartReadings();
    }
}