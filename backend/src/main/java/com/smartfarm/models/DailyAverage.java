package com.smartfarm.models;

public interface DailyAverage {
    String getReadingDay();
    Double getMoisture();
    Double getTemperature();
    Double getHumidity();
}