import {
  DEFAULT_CONTEXT,
  type CrowdLevel,
  type Mood,
  type Place,
  type PlaceCategory,
  type Purpose,
  type RecommendationContext,
  type WeatherCondition
} from "./recommendation-engine";

type LegacyPlace = {
  id?: string;
  name?: string;
  category?: string;
  address?: string;
  lat?: number;
  lng?: number;
  open_now?: boolean;
  travel_time_minutes?: number;
  indoor?: boolean;
  budget?: string;
  route_hint?: string;
  moods?: string[];
  score?: number;
  description?: string;
  reasonTemplate?: string;
  weather_summary?: string;
  aqi_value?: number;
  aqi_status?: string;
};

type RealContextResponse = {
  weather?: {
    weather?: string;
    temperature_c?: number;
    rain_probability?: number;
    summary?: string;
    source?: string;
  };
  air_quality?: {
    aqi?: number;
    status?: string;
    source?: string;
  };
  outdoor_comfort?: string;
  generated_at?: string;
  source_status?: {
    mode?: string;
    error?: string;
    errors?: Record<string, string>;
  };
};

export type RealApiSnapshot = {
  contextSource: "real-api" | "fallback";
  contextUrl: string;
  rawContext?: RealContextResponse;
  nearbyTransitUrl?: string;
  nearbyTransit?: unknown;
  nearbyTransitError?: string;
  error?: string;
};

export type RecommendationRequestContext = {
  lat?: number;
  lon?: number;
  mood?: Mood;
  purpose?: Purpose;
  maxTravelMinutes?: number;
  preferredTags?: string[];
};

const DEFAULT_REAL_CONTEXT = {
  lat: 25.044,
  lon: 121.5294
};

const NEXT_STOPS_API_BASE = process.env.NEXT_STOPS_API_BASE_URL ?? "http://127.0.0.1:8790";

export async function buildContextFromRealApi(
  requestContext: RecommendationRequestContext = {}
): Promise<{ context: RecommendationContext; realApi: RealApiSnapshot }> {
  const lat = requestContext.lat ?? DEFAULT_REAL_CONTEXT.lat;
  const lon = requestContext.lon ?? DEFAULT_REAL_CONTEXT.lon;
  const contextUrl = `${NEXT_STOPS_API_BASE}/api/context?lat=${lat}&lon=${lon}`;

  try {
    const rawContext = await fetchJsonWithTimeout<RealContextResponse>(contextUrl, 15000);
    const transit = await getNearbyTransitSnapshot(lat, lon);

    return {
      context: {
        ...DEFAULT_CONTEXT,
        ...mapRealContextToRecommendationContext(rawContext),
        mood: requestContext.mood ?? DEFAULT_CONTEXT.mood,
        purpose: requestContext.purpose ?? DEFAULT_CONTEXT.purpose,
        maxTravelMinutes: requestContext.maxTravelMinutes ?? DEFAULT_CONTEXT.maxTravelMinutes,
        preferredTags: requestContext.preferredTags ?? DEFAULT_CONTEXT.preferredTags
      },
      realApi: {
        contextSource: rawContext.source_status?.mode === "external" ? "real-api" : "fallback",
        contextUrl,
        rawContext,
        ...transit
      }
    };
  } catch (error) {
    return {
      context: {
        ...DEFAULT_CONTEXT,
        mood: requestContext.mood ?? DEFAULT_CONTEXT.mood,
        purpose: requestContext.purpose ?? DEFAULT_CONTEXT.purpose,
        maxTravelMinutes: requestContext.maxTravelMinutes ?? DEFAULT_CONTEXT.maxTravelMinutes,
        preferredTags: requestContext.preferredTags ?? DEFAULT_CONTEXT.preferredTags
      },
      realApi: {
        contextSource: "fallback",
        contextUrl,
        error: error instanceof Error ? error.message : "Unknown real API error"
      }
    };
  }
}

async function getNearbyTransitSnapshot(lat: number, lon: number) {
  const nearbyTransitUrl = `${NEXT_STOPS_API_BASE}/api/nearby-transit?lat=${lat}&lon=${lon}&radius=800&limit=3`;

  try {
    return {
      nearbyTransitUrl,
      nearbyTransit: await fetchJsonWithTimeout<unknown>(nearbyTransitUrl, 3000)
    };
  } catch (error) {
    return {
      nearbyTransitUrl,
      nearbyTransitError: error instanceof Error ? error.message : "Unknown nearby transit API error"
    };
  }
}

export function normalizePlaces(places: unknown[], origin?: { lat?: number; lon?: number }): Place[] {
  return places
    .filter((place): place is LegacyPlace => Boolean(place) && typeof place === "object")
    .map((place, index) => normalizePlace(place, index, origin));
}

function normalizePlace(place: LegacyPlace, index: number, origin?: { lat?: number; lon?: number }): Place {
  const travelMinutes = toNumber(place.travel_time_minutes, 18);
  const distanceKm =
    origin?.lat && origin?.lon && place.lat && place.lng
      ? round(haversineKm(origin.lat, origin.lon, place.lat, place.lng), 1)
      : round(Math.max(0.8, travelMinutes * 0.18), 1);
  const tags = buildTags(place);

  return {
    id: place.id ?? `place-${index + 1}`,
    name: place.name ?? "Unnamed stop",
    category: mapCategory(place.category, place.indoor),
    isIndoor: Boolean(place.indoor),
    distanceKm,
    travelMinutes,
    estimatedDurationMinutes: estimateDuration(tags, place.category),
    crowdLevel: estimateCrowdLevel(place),
    openNow: place.open_now ?? true,
    tags,
    baseScore: Math.max(18, Math.min(30, Math.round(toNumber(place.score, 76) * 0.3))),
    summary: place.description ?? place.reasonTemplate ?? "A practical stop for the current context.",
    planItems: [
      { title: "Travel", detail: `${travelMinutes} min from here` },
      { title: "Route", detail: place.route_hint ?? "Use nearby transit or a short walk" },
      { title: "Weather", detail: place.weather_summary ?? "Checked by real context API" },
      { title: "Budget", detail: place.budget ? capitalize(place.budget) : "Flexible" }
    ]
  };
}

function mapRealContextToRecommendationContext(rawContext: RealContextResponse): Partial<RecommendationContext> {
  const rainProbability = normalizeRainProbability(rawContext.weather?.rain_probability);
  const temperatureC = toNumber(rawContext.weather?.temperature_c, DEFAULT_CONTEXT.temperatureC);
  const aqi = toNumber(rawContext.air_quality?.aqi, DEFAULT_CONTEXT.aqi);

  return {
    weather: mapWeather(rawContext.weather?.weather, rawContext.outdoor_comfort, rainProbability, temperatureC),
    rainChance: Math.round(rainProbability * 100),
    temperatureC,
    aqi
  };
}

function mapWeather(
  weatherText: string | undefined,
  outdoorComfort: string | undefined,
  rainProbability: number,
  temperatureC: number
): WeatherCondition {
  const text = `${weatherText ?? ""} ${outdoorComfort ?? ""}`.toLowerCase();
  if (rainProbability >= 0.5 || text.includes("rain")) {
    return "rainy";
  }
  if (temperatureC >= 30 || text.includes("hot")) {
    return "hot";
  }
  if (text.includes("clear") || text.includes("sun")) {
    return "sunny";
  }
  return "cloudy";
}

function normalizeRainProbability(value: unknown) {
  const number = toNumber(value, DEFAULT_CONTEXT.rainChance / 100);
  return number > 1 ? Math.min(1, number / 100) : Math.max(0, Math.min(1, number));
}

function buildTags(place: LegacyPlace) {
  const tags = new Set<string>();
  const moodTags: Record<string, string[]> = {
    relaxing_walk: ["relax", "calm", "walk", "nature", "low_effort"],
    solo_quiet: ["calm", "quiet", "low_effort"],
    rainy_backup: ["rain_safe", "calm"],
    photo: ["explore", "art", "walk"],
    date: ["social", "calm"],
    night_out: ["social", "lively", "food"]
  };

  for (const mood of place.moods ?? []) {
    for (const tag of moodTags[mood] ?? []) {
      tags.add(tag);
    }
  }

  if (place.indoor) {
    tags.add("rain_safe");
  } else {
    tags.add("outdoor");
  }

  if (place.budget === "low") {
    tags.add("low_cost");
  }

  const category = `${place.category ?? ""} ${place.description ?? ""}`.toLowerCase();
  if (category.includes("market") || category.includes("food")) {
    tags.add("eat");
    tags.add("food");
  }
  if (category.includes("park") || category.includes("riverside") || category.includes("hike")) {
    tags.add("nature");
    tags.add("walk");
  }
  if (category.includes("gallery") || category.includes("creative")) {
    tags.add("art");
    tags.add("explore");
  }

  return Array.from(tags);
}

function mapCategory(category: string | undefined, indoor: boolean | undefined): PlaceCategory {
  const value = `${category ?? ""}`.toLowerCase();
  if (value.includes("market") || value.includes("food")) {
    return "food";
  }
  if (value.includes("cafe")) {
    return "cafe";
  }
  if (value.includes("gallery") || value.includes("creative")) {
    return "museum";
  }
  if (value.includes("shop")) {
    return "shopping";
  }
  if (indoor) {
    return "wellness";
  }
  return "park";
}

function estimateCrowdLevel(place: LegacyPlace): CrowdLevel {
  const value = `${place.category ?? ""} ${place.description ?? ""}`.toLowerCase();
  if (value.includes("night market") || value.includes("popular")) {
    return "high";
  }
  if (value.includes("quiet") || value.includes("calm") || value.includes("slow")) {
    return "low";
  }
  return "medium";
}

function estimateDuration(tags: string[], category: string | undefined) {
  const value = `${category ?? ""}`.toLowerCase();
  if (tags.includes("food")) {
    return 70;
  }
  if (value.includes("hike")) {
    return 75;
  }
  if (tags.includes("walk")) {
    return 45;
  }
  return 60;
}

async function fetchJsonWithTimeout<T>(url: string, timeoutMs: number): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      cache: "no-store",
      signal: controller.signal
    });

    if (!response.ok) {
      throw new Error(`Real API returned ${response.status}`);
    }

    return (await response.json()) as T;
  } finally {
    clearTimeout(timeout);
  }
}

function toNumber(value: unknown, fallback: number) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number) {
  const radiusKm = 6371;
  const dLat = degreesToRadians(lat2 - lat1);
  const dLon = degreesToRadians(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(degreesToRadians(lat1)) *
      Math.cos(degreesToRadians(lat2)) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  return radiusKm * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function degreesToRadians(value: number) {
  return value * (Math.PI / 180);
}

function round(value: number, digits: number) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
