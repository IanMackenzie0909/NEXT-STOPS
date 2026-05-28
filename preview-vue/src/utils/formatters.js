export function formatTime(minutes) {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours === 0) return `${mins} 分鐘`;
  if (mins === 0) return `${hours} 小時`;
  return `${hours} 小時 ${mins} 分鐘`;
}

export function formatPercent(value) {
  if (value === null || value === undefined || value === "") return "無資料";
  return `${Math.round(Number(value) * 100)}%`;
}

export function formatRainfall(value) {
  if (value === null || value === undefined || value === "") return "近 10 分鐘無資料";
  return `${value} mm`;
}

export function formatUv(uv) {
  const uvIndex = uv?.uv_index;
  if (uvIndex === null || uvIndex === undefined || uvIndex === "") return "無資料";
  const level = uv?.exposure_level ? uvLevelLabel(uv.exposure_level) : "";
  return `${uvIndex}${level ? ` (${level})` : ""}`;
}

export function formatWind(speed, direction) {
  const hasSpeed = speed !== null && speed !== undefined && speed !== "";
  const hasDirection = direction !== null && direction !== undefined && direction !== "";
  if (!hasSpeed && !hasDirection) return "無資料";
  if (!hasDirection) return `${speed} m/s`;
  return `${hasSpeed ? `${speed} m/s，` : ""}${compassDirection(direction)} (${Math.round(Number(direction))} 度)`;
}

export function formatAqi(airQuality) {
  if (!airQuality || airQuality.aqi === null || airQuality.aqi === undefined) return "無資料";
  const status = airQuality.status || "未知";
  const pollutant = airQuality.pollutant ? `，${airQuality.pollutant}` : "";
  return `AQI ${airQuality.aqi} (${status}${pollutant})`;
}

export function formatComfort(value) {
  if (!value) return "無資料";
  const labels = {
    comfortable: "舒適",
    rain_risk: "有降雨風險",
    poor_air_quality: "空氣品質不佳",
    air_quality_watch: "留意空氣品質",
    extreme_uv: "紫外線危險級",
    very_high_uv: "紫外線過量級",
    high_uv: "紫外線偏高",
    hot: "天氣偏熱",
    warm: "天氣偏暖",
    windy: "風勢較強",
  };
  return labels[value] || titleCase(String(value).replaceAll("_", " "));
}

export function formatWeatherNow(context) {
  const weather = context?.weather || {};
  const parts = [];
  if (weather.weather) parts.push(weather.weather);
  if (weather.temperature_c !== null && weather.temperature_c !== undefined) {
    parts.push(`${weather.temperature_c}°C`);
  }
  parts.push(`降雨機率 ${formatPercent(weather.rain_probability)}`);
  if (weather.wind_speed_mps !== null && weather.wind_speed_mps !== undefined) {
    parts.push(`風速 ${weather.wind_speed_mps} m/s`);
  }
  return parts.join("，");
}

export function weatherClass(status) {
  if (status === "suitable" || status === "any") return "ok";
  if (status === "watch") return "warn";
  return "cool";
}

export function aqiClass(status) {
  if (status === "good" || status === "良好") return "ok";
  if (status === "moderate" || status === "普通") return "warn";
  return "warn";
}

export function budgetLabel(value) {
  if (value === "low") return "低消費";
  if (value === "flexible") return "預算彈性";
  return "中等消費";
}

export function uvLevelLabel(value) {
  const labels = {
    low: "低量級",
    moderate: "中量級",
    high: "高量級",
    very_high: "過量級",
    extreme: "危險級",
  };
  return labels[value] || titleCase(String(value).replaceAll("_", " "));
}

export function titleCase(value) {
  return String(value)
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function compassDirection(degrees) {
  const directions = ["北", "北北東", "東北", "東北東", "東", "東南東", "東南", "南南東", "南", "南南西", "西南", "西南西", "西", "西北西", "西北", "北北西"];
  const index = Math.round(Number(degrees) / 22.5) % 16;
  return directions[index] || "北";
}
