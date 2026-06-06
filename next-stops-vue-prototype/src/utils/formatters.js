export function formatTime(minutes) {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (!hours) return `${mins} 分鐘`;
  if (!mins) return `${hours} 小時`;
  return `${hours} 小時 ${mins} 分鐘`;
}

export function commuteParts(commute, fallbackMinutes = 0) {
  const duration = commute?.duration_text || (fallbackMinutes ? `${fallbackMinutes} 分鐘` : "時間待估");
  const mode = commute?.mode_label || "路線";
  return {
    duration,
    mode,
    icon: transportIcon(commute?.mode, mode),
  };
}

export function transportIcon(mode, label = "") {
  const text = `${mode || ""} ${label || ""}`.toLowerCase();
  if (/walk|步行|走路/.test(text)) return "walk";
  if (/driv|開車|自駕|car/.test(text)) return "car";
  if (/bus|公車/.test(text)) return "bus";
  if (/mrt|metro|捷運|rail|train|火車|大眾/.test(text)) return "train";
  if (/transit/.test(text)) return "train";
  return "map";
}

export function weatherChips(context, fallbackSummary = "") {
  const weather = context?.weather || {};
  const chips = [];
  const rain = normalizedRainPercent(weather.rain_probability);
  const temp = numberOrNull(weather.temperature_c);
  const wind = numberOrNull(weather.wind_speed_mps);
  const condition = weather.weather || conditionFromSummary(weather.summary || fallbackSummary);

  if (condition) {
    chips.push({
      key: "condition",
      icon: weatherConditionIcon(condition, rain),
      label: condition,
      className: "weather-condition",
    });
  }
  if (temp !== null) {
    chips.push({
      key: "temperature",
      icon: "thermometer",
      label: `${formatNumber(temp)}°C`,
      className: `weather-temp temp-${temperatureTone(temp)}`,
    });
  }
  if (rain !== null) {
    chips.push({
      key: "rain",
      icon: "rain",
      label: `${rain}%`,
      className: "weather-rain",
    });
  }
  if (wind !== null) {
    chips.push({
      key: "wind",
      icon: "wind",
      label: `${formatNumber(wind)} m/s`,
      className: "weather-wind",
    });
  }
  if (!chips.length && fallbackSummary) {
    chips.push({
      key: "summary",
      icon: "cloud",
      label: fallbackSummary,
      className: "weather-condition",
    });
  }
  return chips;
}

export function aqiChip(context, fallbackValue = 65, fallbackStatus = "大台北") {
  const air = context?.air_quality || {};
  const value = air.aqi ?? (fallbackValue === "--" || fallbackValue === "unknown" ? 65 : fallbackValue);
  const status = air.status_kind || air.status || fallbackStatus;
  const numeric = Number(value);
  let tone = aqiToneFromStatus(status);
  if (Number.isFinite(numeric)) {
    if (numeric <= 50) tone = "good";
    else if (numeric <= 100) tone = "moderate";
    else if (numeric <= 150) tone = "sensitive";
    else if (numeric <= 200) tone = "unhealthy";
    else if (numeric <= 300) tone = "very-unhealthy";
    else tone = "hazardous";
  }
  return {
    key: "aqi",
    icon: "aqi",
    label: Number.isFinite(numeric) ? `AQI ${numeric}` : "AQI --",
    detail: statusLabel(air.status || status),
    className: `aqi-${tone}`,
  };
}

export function openingLabel(place) {
  if (place?.open_now === false) return "可能未營業";
  if (place?.open_now === true) return "目前可安排";
  return "營業狀態待確認";
}

export function suitabilityLabel(place) {
  const score = Number(place?.score);
  if (Number.isFinite(score) && score >= 72) return "很符合當下";
  if (place?.weather_status === "watch") return "天氣需留意";
  if (Number.isFinite(score) && score < 55) return "可當備選";
  return "初步適合";
}

export function budgetLabel(value) {
  if (value === "low") return "低消費";
  if (value === "flexible") return "預算彈性";
  return "中等消費";
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function normalizedRainPercent(value) {
  const number = numberOrNull(value);
  if (number === null) return null;
  return Math.round(number <= 1 ? number * 100 : number);
}

function formatNumber(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function temperatureTone(value) {
  if (value < 18) return "cold";
  if (value < 26) return "mild";
  if (value < 30) return "warm";
  return "hot";
}

function conditionFromSummary(summary) {
  if (!summary) return "";
  const first = String(summary).split(/[,/，、]/)[0]?.trim();
  return first && !/^\d/.test(first) ? first : "";
}

function weatherConditionIcon(condition, rainPercent) {
  if (rainPercent !== null && rainPercent >= 45) return "rain";
  if (/雨|rain|shower|storm/i.test(condition)) return "rain";
  if (/晴|sun|clear/i.test(condition)) return "sun";
  if (/陰|雲|cloud|overcast/i.test(condition)) return "cloud";
  return "cloud";
}

function statusLabel(status) {
  const text = String(status || "").toLowerCase();
  if (text === "good" || /良好/.test(status)) return "良好";
  if (text === "moderate" || /普通/.test(status)) return "普通";
  if (text === "sensitive" || /敏感/.test(status)) return "敏感";
  if (text === "unhealthy" || /所有|不健康/.test(status)) return "不健康";
  if (text === "very_unhealthy" || text === "very-unhealthy" || /非常/.test(status)) return "非常不健康";
  if (text === "hazardous" || /危害|危險/.test(status)) return "危害";
  if (text === "poor" || /差|敏感|不健康/.test(status)) return "需留意";
  return status || "待確認";
}

function aqiToneFromStatus(status) {
  const text = String(status || "").toLowerCase().replace("_", "-");
  if (text === "good" || /良好/.test(status)) return "good";
  if (text === "moderate" || /普通/.test(status)) return "moderate";
  if (text === "sensitive" || /敏感/.test(status)) return "sensitive";
  if (text === "unhealthy" || /所有族群|不健康/.test(status)) return "unhealthy";
  if (text === "very-unhealthy" || /非常/.test(status)) return "very-unhealthy";
  if (text === "hazardous" || /危害|危險/.test(status)) return "hazardous";
  return "unknown";
}
