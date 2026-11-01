package com.smartfarm.repositories;

import com.smartfarm.models.WeatherForecast;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface WeatherForecastRepository extends JpaRepository<WeatherForecast, Long> {

    // Gets the most recent weather forecast — needed later in Step 7
    WeatherForecast findTopByOrderByFetchedAtDesc();
}