export function formatTime(minutes) {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (!hours) return `${mins} 分鐘`;
  if (!mins) return `${hours} 小時`;
  return `${hours} 小時 ${mins} 分鐘`;
}

export function formatWeatherNow(context) {
  const weather = context?.weather || {};
  const parts = [];
  if (weather.weather) parts.push(weather.weather);
  if (weather.temperature_c !== null && weather.temperature_c !== undefined) parts.push(`${weather.temperature_c}°C`);
  if (weather.rain_probability !== null && weather.rain_probability !== undefined) parts.push(`雨 ${Math.round(Number(weather.rain_probability) * 100)}%`);
  return parts.length ? parts.join(" / ") : "即時情境尚未取得";
}

export function budgetLabel(value) {
  if (value === "low") return "低消費";
  if (value === "flexible") return "預算彈性";
  return "中等消費";
}
