export const MOODS = [
  { id: "relaxing_walk", label: "散步放鬆", icon: "散步" },
  { id: "date", label: "約會", icon: "約會" },
  { id: "solo_quiet", label: "一個人安靜", icon: "安靜" },
  { id: "photo", label: "拍照探索", icon: "拍照" },
  { id: "rainy_backup", label: "雨天備案", icon: "雨天" },
  { id: "night_out", label: "夜晚出門", icon: "夜晚" },
];

export const LOCATION_LABELS = {
  taipei_main: "台北車站",
  xinyi: "信義區",
  daan: "大安森林公園",
  songshan: "松山",
};

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

export const PRESETS = {
  evening: {
    label: "傍晚散步 / 90 分鐘",
    mood: "relaxing_walk",
    time: 90,
    distance: 25,
    weatherPreference: "any",
    budget: "low",
  },
  date: {
    label: "約會夜晚 / 3 小時",
    mood: "date",
    time: 180,
    distance: 35,
    weatherPreference: "any",
    budget: "flexible",
  },
  rainy: {
    label: "雨天室內",
    mood: "rainy_backup",
    time: 120,
    distance: 20,
    weatherPreference: "indoor",
    budget: "medium",
  },
  solo: {
    label: "一個人安靜 / 2 小時",
    mood: "solo_quiet",
    time: 120,
    distance: 30,
    weatherPreference: "avoid_rain",
    budget: "low",
  },
};
