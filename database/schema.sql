CREATE DATABASE IF NOT EXISTS agritwin_db;
USE agritwin_db;

CREATE TABLE IF NOT EXISTS sensor_readings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    moisture DOUBLE NOT NULL,
    temperature DOUBLE NOT NULL,
    humidity DOUBLE NOT NULL,
    reading_time DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS weather_forecast (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    rain_mm DOUBLE,
    temp DOUBLE,
    humidity DOUBLE,
    rain_chance_percent DOUBLE,
    forecast_time DATETIME,
    fetched_at DATETIME
);