package com.smartfarm.controllers;

import com.smartfarm.models.SensorReading;
import com.smartfarm.services.SensorReadingService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/sensor-data")
public class SensorReadingController {

    @Autowired
    private SensorReadingService sensorReadingService;

    @PostMapping
    public ResponseEntity<SensorReading> receiveSensorData(@RequestBody SensorReading reading) {
        SensorReading saved = sensorReadingService.saveReading(reading);
        return ResponseEntity.ok(saved);
    }
}