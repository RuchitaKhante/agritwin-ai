package com.smartfarm.models;

public record DailyReading(String date, double moisture, double temperature, double humidity) {}