export type PlaceCategory =
  | "park"
  | "museum"
  | "cafe"
  | "library"
  | "shopping"
  | "food"
  | "wellness";

export type CrowdLevel = "low" | "medium" | "high";
export type WeatherCondition = "sunny" | "cloudy" | "rainy" | "hot";
export type Mood = "tired" | "focused" | "social" | "restless";
export type Purpose = "relax" | "work" | "explore" | "exercise" | "eat";

export type Place = {
  id: string;
  name: string;
  category: PlaceCategory;
  isIndoor: boolean;
  distanceKm: number;
  travelMinutes: number;
  estimatedDurationMinutes: number;
  crowdLevel: CrowdLevel;
  openNow: boolean;
  tags: string[];
  baseScore: number;
  summary: string;
  planItems?: Array<{ title: string; detail: string }>;
};

export type RecommendationContext = {
  weather: WeatherCondition;
  rainChance: number;
  temperatureC: number;
  aqi: number;
  mood: Mood;
  purpose: Purpose;
  maxTravelMinutes: number;
  preferredTags: string[];
};

export type UserWeights = {
  weather: number;
  aqi: number;
  distance: number;
  availability: number;
  mood: number;
  purpose: number;
  crowd: number;
  preference: number;
};

export type ScoreContribution = {
  key: keyof UserWeights | "base";
  label: string;
  points: number;
  reason: string;
};

export type RecommendationResult = {
  place: Place;
  score: number;
  summary: string;
  reasons: string[];
  scoreBreakdown: ScoreContribution[];
  chips: string[];
  planItems: Array<{ title: string; detail: string }>;
};

export const DEFAULT_CONTEXT: RecommendationContext = {
  weather: "cloudy",
  rainChance: 12,
  temperatureC: 24,
  aqi: 48,
  mood: "tired",
  purpose: "relax",
  maxTravelMinutes: 30,
  preferredTags: ["calm", "nature", "low_effort"]
};

export const DEFAULT_USER_WEIGHTS: UserWeights = {
  weather: 1,
  aqi: 1,
  distance: 1,
  availability: 1,
  mood: 1,
  purpose: 1,
  crowd: 1,
  preference: 1
};

export const DEMO_PLACES: Place[] = [
  {
    id: "riverside-botanical-walk",
    name: "Riverside Botanical Walk",
    category: "park",
    isIndoor: false,
    distanceKm: 2.1,
    travelMinutes: 12,
    estimatedDurationMinutes: 38,
    crowdLevel: "low",
    openNow: true,
    tags: ["calm", "nature", "walk", "low_effort", "relax"],
    baseScore: 24,
    summary: "Low crowd, soft weather, and a gentle 38-minute reset.",
    planItems: [
      { title: "Best time", detail: "Within the next 90 minutes" },
      { title: "Bring", detail: "Light jacket, water" },
      { title: "Weather", detail: "Cloudy, comfortable, low rain" },
      { title: "Energy fit", detail: "Low effort, high reset" }
    ]
  },
  {
    id: "central-library-reading-room",
    name: "Central Library Reading Room",
    category: "library",
    isIndoor: true,
    distanceKm: 1.6,
    travelMinutes: 10,
    estimatedDurationMinutes: 60,
    crowdLevel: "medium",
    openNow: true,
    tags: ["calm", "focused", "rain_safe", "work", "low_effort"],
    baseScore: 21,
    summary: "Quiet indoor space for a focused reset without much travel."
  },
  {
    id: "design-museum-courtyard",
    name: "Design Museum Courtyard",
    category: "museum",
    isIndoor: true,
    distanceKm: 4.4,
    travelMinutes: 24,
    estimatedDurationMinutes: 75,
    crowdLevel: "medium",
    openNow: true,
    tags: ["explore", "art", "rain_safe", "calm"],
    baseScore: 22,
    summary: "A weather-safe cultural stop with a relaxed indoor pace."
  },
  {
    id: "night-market-lane",
    name: "Night Market Lane",
    category: "food",
    isIndoor: false,
    distanceKm: 5.8,
    travelMinutes: 34,
    estimatedDurationMinutes: 70,
    crowdLevel: "high",
    openNow: false,
    tags: ["social", "eat", "lively", "outdoor"],
    baseScore: 28,
    summary: "A lively food stop, better for social evenings than calm mornings."
  }
];

export function getRecommendations({
  places,
  context = DEFAULT_CONTEXT,
  weights = DEFAULT_USER_WEIGHTS
}: {
  places: Place[];
  context?: RecommendationContext;
  weights?: UserWeights;
}): RecommendationResult[] {
  return places
    .map((place) => scorePlace(place, context, weights))
    .filter((result) => result.score > 0)
    .sort((a, b) => b.score - a.score);
}

export function scorePlace(
  place: Place,
  context: RecommendationContext,
  weights: UserWeights = DEFAULT_USER_WEIGHTS
): RecommendationResult {
  const breakdown: ScoreContribution[] = [
    {
      key: "base",
      label: "Base fit",
      points: place.baseScore,
      reason: "Baseline quality and general relevance for this place."
    },
    weighted("weather", "Weather fit", scoreWeather(place, context), weights.weather),
    weighted("aqi", "Air quality", scoreAirQuality(place, context), weights.aqi),
    weighted("distance", "Distance", scoreDistance(place, context), weights.distance),
    weighted("availability", "Open now", scoreAvailability(place), weights.availability),
    weighted("mood", "Mood fit", scoreMood(place, context), weights.mood),
    weighted("purpose", "Purpose fit", scorePurpose(place, context), weights.purpose),
    weighted("crowd", "Crowd level", scoreCrowd(place), weights.crowd),
    weighted("preference", "Preference match", scorePreference(place, context), weights.preference)
  ];

  const rawScore = breakdown.reduce((total, item) => total + item.points, 0);
  const score = clamp(Math.round(rawScore), 0, 100);

  return {
    place,
    score,
    summary: place.summary,
    reasons: buildReasons(breakdown),
    scoreBreakdown: breakdown,
    chips: buildChips(place, context),
    planItems: buildPlanItems(place, context)
  };
}

function weighted(
  key: keyof UserWeights,
  label: string,
  contribution: Omit<ScoreContribution, "key" | "label">,
  weight: number
): ScoreContribution {
  return {
    key,
    label,
    points: Math.round(contribution.points * weight),
    reason: contribution.reason
  };
}

function scoreWeather(place: Place, context: RecommendationContext) {
  if (context.rainChance >= 60 && !place.isIndoor) {
    return { points: -24, reason: "Rain risk is high, so outdoor stops are deprioritized." };
  }

  if (context.rainChance >= 60 && (place.isIndoor || place.tags.includes("rain_safe"))) {
    return { points: 18, reason: "Rain risk is high, so indoor or rain-safe places move up." };
  }

  if (context.weather === "hot" && !place.isIndoor) {
    return { points: -12, reason: "Hot weather makes longer outdoor stops less suitable." };
  }

  if (context.temperatureC >= 18 && context.temperatureC <= 26) {
    return { points: 8, reason: "The current temperature is comfortable for this stop." };
  }

  return { points: 0, reason: "Weather does not strongly change this recommendation." };
}

function scoreAirQuality(place: Place, context: RecommendationContext) {
  if (context.aqi > 100 && !place.isIndoor) {
    const durationPenalty = place.estimatedDurationMinutes > 45 ? -8 : 0;
    return {
      points: -18 + durationPenalty,
      reason: "AQI is elevated, so outdoor activity is reduced in priority."
    };
  }

  if (context.aqi <= 50 && !place.isIndoor) {
    return { points: 6, reason: "Air quality is good enough for an outdoor reset." };
  }

  if (context.aqi > 100 && place.isIndoor) {
    return { points: 8, reason: "Indoor places are safer when AQI is elevated." };
  }

  return { points: 0, reason: "Air quality is acceptable and does not change the ranking much." };
}

function scoreDistance(place: Place, context: RecommendationContext) {
  const overLimit = place.travelMinutes - context.maxTravelMinutes;

  if (overLimit <= 0) {
    return { points: 10, reason: "Travel time is inside the current acceptable range." };
  }

  return {
    points: -Math.min(26, Math.round(overLimit * 1.4)),
    reason: "Travel time is longer than the current context prefers."
  };
}

function scoreAvailability(place: Place) {
  if (!place.openNow) {
    return { points: -100, reason: "This place is currently closed." };
  }

  return { points: 6, reason: "This place is open now." };
}

function scoreMood(place: Place, context: RecommendationContext) {
  const moodTags: Record<Mood, string[]> = {
    tired: ["calm", "low_effort", "wellness"],
    focused: ["focused", "work", "quiet"],
    social: ["social", "lively", "food"],
    restless: ["walk", "explore", "exercise"]
  };

  const matches = countMatches(place.tags, moodTags[context.mood]);
  return {
    points: Math.min(12, matches * 6),
    reason: matches > 0 ? "This place matches the user's current mood." : "Mood fit is neutral."
  };
}

function scorePurpose(place: Place, context: RecommendationContext) {
  const purposeTags: Record<Purpose, string[]> = {
    relax: ["relax", "calm", "nature", "wellness"],
    work: ["work", "focused", "quiet"],
    explore: ["explore", "art", "walk"],
    exercise: ["exercise", "walk", "outdoor"],
    eat: ["eat", "food", "cafe"]
  };

  const matches = countMatches(place.tags, purposeTags[context.purpose]);
  return {
    points: Math.min(10, matches * 5),
    reason: matches > 0 ? "This stop supports the user's current purpose." : "Purpose fit is neutral."
  };
}

function scoreCrowd(place: Place) {
  if (place.crowdLevel === "low") {
    return { points: 10, reason: "Crowd level is low, so this stop should feel easier." };
  }

  if (place.crowdLevel === "high") {
    return { points: -12, reason: "Crowd level is high, so this stop is less calm." };
  }

  return { points: 0, reason: "Crowd level is moderate." };
}

function scorePreference(place: Place, context: RecommendationContext) {
  const matches = countMatches(place.tags, context.preferredTags);
  return {
    points: Math.min(8, matches * 4),
    reason: matches > 0 ? "This place matches saved user preferences." : "No saved preference match."
  };
}

function buildReasons(breakdown: ScoreContribution[]) {
  return breakdown
    .filter((item) => item.key !== "base" && item.points > 0)
    .sort((a, b) => b.points - a.points)
    .slice(0, 4)
    .map((item) => item.reason);
}

function buildChips(place: Place, context: RecommendationContext) {
  const crowd = place.crowdLevel === "low" ? "Low crowd" : `${capitalize(place.crowdLevel)} crowd`;
  return [`${context.temperatureC} C`, `${place.distanceKm} km`, crowd];
}

function buildPlanItems(place: Place, context: RecommendationContext) {
  if (place.planItems?.length) {
    return place.planItems;
  }

  return [
    {
      title: "Best time",
      detail: context.rainChance > 50 ? "After rain eases" : "Within the next 90 minutes"
    },
    { title: "Travel", detail: `${place.travelMinutes} min from here` },
    {
      title: "Weather",
      detail: context.rainChance > 50 ? "Rain-safe option preferred" : "Comfortable conditions"
    },
    { title: "Energy fit", detail: place.tags.includes("low_effort") ? "Low effort" : "Moderate effort" }
  ];
}

function countMatches(values: string[], candidates: string[]) {
  const valueSet = new Set(values);
  return candidates.filter((candidate) => valueSet.has(candidate)).length;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
