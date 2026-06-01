import { NextResponse } from "next/server";
import legacyPlaces from "../../../next-stops-api/data/places.json";
import savedPlaces from "../../../next-stops-api/data/saved_places.json";
import { buildContextFromRealApi, normalizePlaces, type RecommendationRequestContext } from "../../../lib/real-api-adapter";
import {
  DEFAULT_CONTEXT,
  DEFAULT_USER_WEIGHTS,
  DEMO_PLACES,
  getRecommendations,
  type Place,
  type UserWeights
} from "../../../lib/recommendation-engine";

type RecommendationRequest = {
  context?: RecommendationRequestContext;
  filters?: {
    query?: string;
    openNowOnly?: boolean;
  };
  useRealContext?: boolean;
  weights?: Partial<UserWeights>;
  places?: Place[];
};

export async function GET() {
  return NextResponse.json(await buildRecommendationResponse({ useRealContext: true }));
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  return NextResponse.json(await buildRecommendationResponse(body));
}

async function buildRecommendationResponse(body: RecommendationRequest) {
  const { context, realApi } =
    body.useRealContext === false
      ? {
          context: {
            ...DEFAULT_CONTEXT,
            mood: body.context?.mood ?? DEFAULT_CONTEXT.mood,
            purpose: body.context?.purpose ?? DEFAULT_CONTEXT.purpose,
            maxTravelMinutes: body.context?.maxTravelMinutes ?? DEFAULT_CONTEXT.maxTravelMinutes,
            preferredTags: body.context?.preferredTags ?? DEFAULT_CONTEXT.preferredTags
          },
          realApi: {
            contextSource: "fallback" as const,
            contextUrl: "disabled by request"
          }
        }
      : await buildContextFromRealApi(body.context);
  const weights = {
    ...DEFAULT_USER_WEIGHTS,
    ...body.weights
  };

  const storedPlaces = Array.isArray(savedPlaces) ? (savedPlaces as Place[]) : [];
  const normalizedLegacyPlaces = normalizePlaces(Array.isArray(legacyPlaces) ? legacyPlaces : [], {
    lat: body.context?.lat,
    lon: body.context?.lon
  });
  const candidatePlaces = body.places?.length
    ? body.places
    : storedPlaces.length
      ? storedPlaces
      : normalizedLegacyPlaces.length
        ? normalizedLegacyPlaces
        : DEMO_PLACES;
  const places = filterPlaces(candidatePlaces, body.filters);
  const recommendations = getRecommendations({ places, context, weights });

  return {
    generatedAt: new Date().toISOString(),
    context,
    weights,
    realApi,
    recommendations,
    explainability: {
      model: "rule-based scoring",
      scoreRange: "0-100",
      notes: [
        "Each place starts with a base fit score.",
        "Weather, AQI, distance, opening status, mood, purpose, crowd, and saved preferences add or subtract points.",
        "User weights can personalize the importance of each factor while keeping the result explainable."
      ]
    }
  };
}

function filterPlaces(
  places: Place[],
  filters: RecommendationRequest["filters"] = {}
) {
  const query = filters.query?.trim().toLowerCase();

  return places.filter((place) => {
    if (filters.openNowOnly && !place.openNow) {
      return false;
    }

    if (!query) {
      return true;
    }

    const haystack = [
      place.name,
      place.category,
      place.summary,
      place.tags.join(" ")
    ].join(" ").toLowerCase();

    return haystack.includes(query);
  });
}
