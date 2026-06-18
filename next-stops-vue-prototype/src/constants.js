export const MOODS = [
  { id: "relaxing_walk", label: "散步放鬆", short: "Reset" },
  { id: "date", label: "約會", short: "Date" },
  { id: "solo_quiet", label: "一個人安靜", short: "Quiet" },
  { id: "photo", label: "拍照探索", short: "Photo" },
  { id: "rainy_backup", label: "雨天備案", short: "Rain" },
  { id: "night_out", label: "夜晚出門", short: "Night" },
];

export const LOCATION_FALLBACK_LABEL = "台北車站";
export const LOCATION_FALLBACK_COORDS = {
  lat: 25.0478,
  lon: 121.517,
};

export const SERVICE_AREA_LABEL = "雙北地區";
export const SERVICE_AREA_NOTICE = "NEXT STOPS 目前暫定服務區域為臺北市與新北市。你仍可使用預設的台北車站，或已儲存於雙北地區內的常用起點。";

export const WEATHER_LABELS = {
  any: "戶外也可以",
  indoor: "想待在室內",
  avoid_rain: "避開下雨風險",
};

export const BUDGET_LABELS = {
  low: "低預算",
  medium: "中等預算",
  flexible: "預算彈性",
};

export const TRANSPORT_MODES = [
  { id: "car", label: "開車", icon: "car" },
  { id: "bus", label: "公車", icon: "bus" },
  { id: "mrt", label: "捷運", icon: "train" },
  { id: "motorcycle", label: "機車", icon: "scooter" },
  { id: "walking", label: "步行", icon: "walk" },
  { id: "bicycle", label: "腳踏車", icon: "bicycle" },
];
