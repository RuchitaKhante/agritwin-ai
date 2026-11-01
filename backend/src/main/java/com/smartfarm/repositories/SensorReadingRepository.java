package com.smartfarm.repositories;

import com.smartfarm.models.SensorReading;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import org.springframework.data.jpa.repository.Query;
import com.smartfarm.models.DailyAverage;

import java.util.List;

@Repository
public interface SensorReadingRepository extends JpaRepository<SensorReading, Long> {

    SensorReading findTopByOrderByReadingTimeDesc();

    List<SensorReading> findTop5ByOrderByReadingTimeDesc();

    // NEW: more points for a smoother chart
    List<SensorReading> findTop15ByOrderByReadingTimeDesc();

    // NEW: last 60 readings for the live sensor graph
    List<SensorReading> findTop60ByOrderByReadingTimeDesc();

    @Query(value = "SELECT DATE_FORMAT(reading_time, '%Y-%m-%d') AS readingDay, " +
            "AVG(moisture) AS moisture, AVG(temperature) AS temperature, AVG(humidity) AS humidity " +
            "FROM sensor_readings GROUP BY DATE_FORMAT(reading_time, '%Y-%m-%d') " +
            "ORDER BY readingDay DESC LIMIT 10", nativeQuery = true)
    List<DailyAverage> findRecentDailyAverages();
}