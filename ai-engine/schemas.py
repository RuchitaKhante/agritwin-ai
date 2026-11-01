# schemas.py - request/response models for the FastAPI service.
# They validate input (-> HTTP 422 on bad data) and make Swagger (/docs) show the REAL response shape.

from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

Condition = Literal["critical", "dry", "normal", "wet"]
StressLevel = Literal["healthy", "warning", "critical"]
Scenario = Literal["irrigate_now", "rain_tomorrow", "reduce_20pct", "delay_24h"]
NextStatus = Literal["predicted", "beyond_forecast_horizon", "unavailable"]


# ------------------------------- requests -------------------------------
class SensorReading(BaseModel):
    moisture: float = Field(ge=0, le=100, description="Soil moisture, % (already converted from raw ADC)")
    temperature: float = Field(ge=-30, le=70, description="Air/soil temperature, deg C")
    humidity: float = Field(ge=0, le=100, description="Relative humidity, %")
    timestamp: str = Field(min_length=1, description="ISO-8601 time of the reading")
    rain_chance_percent: Optional[float] = Field(default=None, ge=0, le=100)


class WeatherForecast(BaseModel):
    temperature: float = Field(ge=-30, le=70)
    rain_chance_percent: float = Field(ge=0, le=100)
    forecast_time: Optional[str] = None


class DailyForecast(BaseModel):
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    temperature: float = Field(ge=-30, le=70, description="Mean daily temperature, deg C")
    rain_chance_percent: float = Field(ge=0, le=100)
    humidity: Optional[float] = Field(default=None, ge=0, le=100)


class AnalyzeRequest(BaseModel):
    sensor_history: List[SensorReading] = Field(min_length=1)
    weather_forecast: WeatherForecast
    daily_forecast: Optional[List[DailyForecast]] = None
    session_id: str = Field(default="default", min_length=1, max_length=64,
                            description="Lets /chat find this analysis. Optional; defaults to 'default'.")


class SimulateRequest(BaseModel):
    sensor_history: List[SensorReading] = Field(min_length=1)
    weather_forecast: WeatherForecast
    scenario: Scenario
    daily_forecast: Optional[List[DailyForecast]] = None
    amount_mm: float = Field(default=20.0, gt=0, le=100, description="Water applied in the irrigation scenarios")


class ChatRequest(BaseModel):
    # `message` is the documented name; `question` / `query` are accepted too so a slightly different client still works.
    message: str = Field(min_length=1, max_length=2000, validation_alias=AliasChoices("message", "question", "query"))
    session_id: str = Field(default="default", min_length=1, max_length=64)
    # Optional: send fresh data with the question; otherwise the latest /analyze for the session is used.
    sensor_history: Optional[List[SensorReading]] = None
    weather_forecast: Optional[WeatherForecast] = None
    daily_forecast: Optional[List[DailyForecast]] = None
    tomorrow_forecast: Optional[WeatherForecast] = None
    crop: Optional[str] = Field(default=None, max_length=60)


# ------------------------------- responses -------------------------------
class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class ForecastPoint(_Out):
    step: int
    hours_ahead: int
    date: Optional[str] = None
    label: str
    weekday: Optional[str] = None
    moisture: float
    lower: Optional[float] = None
    upper: Optional[float] = None
    condition: Condition
    rain_chance_percent: float


class TimeTo(_Out):
    steps: int
    hours: int
    date: Optional[str] = None
    moisture: float


class StressPoint(_Out):
    step: int
    date: Optional[str] = None
    label: str
    weekday: Optional[str] = None
    moisture: float
    level: StressLevel


class StressAlert(_Out):
    active: bool
    severity: Literal["none", "moderate", "severe"]
    in_days: Optional[int] = None
    message: str
    already_critical: bool = False
    detail: Optional[str] = None


class DepthMM(_Out):
    estimate: float
    min: float
    max: float


class IrrigationWindow(_Out):
    day_offset: int
    date: Optional[str] = None
    date_label: Optional[str] = None
    label: str
    start: str
    end: Optional[str] = None
    display: str
    depth_mm: DepthMM
    moisture_before: float
    reason: str


class Irrigation(_Out):
    needed: bool
    urgency: Literal["now", "soon", "later", "none"]
    windows: List[IrrigationWindow]
    notes: List[str]
    assumptions: Dict[str, float]


class WeatherDay(_Out):
    date: Optional[str] = None
    temperature: float
    humidity: float
    rain_chance_percent: float


class Thresholds(_Out):
    critical_below: float
    dry_below: float
    wet_above: float


class SoilHealthBreakdown(_Out):
    score: float
    components: Dict[str, float]
    ideal: Dict[str, float]


class AnalyzeResponse(_Out):
    current_status: Literal["dry", "moist", "wet"]
    projected_trend: str
    soil_health_score: float
    soil_health_breakdown: SoilHealthBreakdown
    crop_stress: bool
    shap_explanation: Dict[str, float]
    advisory: str
    soil_condition: Condition
    current_moisture: float
    step_hours: int
    thresholds: Thresholds
    forecast: List[ForecastPoint]
    forecast_with_plan: List[float]
    time_to_dry: Optional[TimeTo] = None
    time_to_critical: Optional[TimeTo] = None
    water_stress_outlook: List[StressPoint]
    water_stress_alert: StressAlert
    irrigation: Irrigation
    weather_outlook: List[WeatherDay]
    warnings: List[str]
    model_info: Dict[str, str | int]
    # ---- next irrigation ("if I irrigate now, when do I irrigate again?"); separate from the current-irrigation fields ----
    next_irrigation_status: NextStatus = "unavailable"
    next_irrigation_date: Optional[str] = Field(default=None, description="YYYY-MM-DD, or null when not predicted")
    days_until_irrigation: Optional[int] = Field(default=None, description="Days counted from next_irrigation_reference_date (date of the latest sensor reading)")
    next_irrigation_reference_date: Optional[str] = None
    next_irrigation_basis: Optional[Literal["after_current_irrigation", "no_irrigation_needed_now"]] = None
    irrigation_required_now: Optional[bool] = None
    moisture_after_current_irrigation: Optional[float] = None
    next_irrigation_trigger_moisture: float = 25.0
    next_irrigation_message: str = ""
    forecast_days_until_irrigation: Optional[int] = Field(default=None, description="Day count from the moisture forecast alone, before the category window is applied")
    next_irrigation_days_window: Optional[List[int]] = Field(default=None, description="[min,max] days allowed for the current soil category")
    next_irrigation_source: Optional[Literal["forecast", "category_window"]] = None
    next_irrigation_reason: str = ""
    next_irrigation_xai: Dict[str, Any] = Field(default_factory=dict)
    predicted_moisture_trend: List[Dict[str, Any]] = Field(default_factory=list)


class TrendSummary(_Out):
    current_status: Literal["dry", "moist", "wet"]
    projected_trend: str


class Comparison(_Out):
    min_moisture_baseline: float
    min_moisture_simulated: float
    day7_difference: float
    days_to_dry_baseline: Optional[int] = None
    days_to_dry_simulated: Optional[int] = None


class SimulateResponse(_Out):
    scenario: Scenario
    amount_mm: Optional[float] = None
    baseline: TrendSummary
    simulated: TrendSummary
    baseline_forecast: List[ForecastPoint]
    simulated_forecast: List[ForecastPoint]
    comparison: Comparison
    baseline_next_irrigation: Optional[Dict[str, Any]] = Field(default=None, description="Hypothetical: no irrigation")
    simulated_next_irrigation: Optional[Dict[str, Any]] = Field(default=None, description="Hypothetical: the chosen scenario")


class ChatResponse(_Out):
    answer: str
    sources: List[str]
    live_data_used: bool
    warning: Optional[str] = None