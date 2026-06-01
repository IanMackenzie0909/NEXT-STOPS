"use client";

import { useEffect, useState } from "react";
import {
  DetailScreen,
  HomeScreen,
  PlanScreen,
  Screen,
  WelcomeScreen,
  type RecommendationControls
} from "../components/ui";
import type { RecommendationContext, RecommendationResult } from "../lib/recommendation-engine";

type RecommendationApiResponse = {
  context: RecommendationContext;
  recommendations: RecommendationResult[];
};

const DEFAULT_RECOMMENDATION_CONTROLS: RecommendationControls = {
  query: "",
  openNowOnly: true,
  mood: "tired",
  purpose: "relax",
  maxTravelMinutes: 30,
  preferredTagsText: "calm, nature, low_effort",
  preferenceWeight: 1
};

export default function Page() {
  const [screen, setScreen] = useState<Screen>("welcome");
  const [context, setContext] = useState<RecommendationContext | null>(null);
  const [recommendation, setRecommendation] = useState<RecommendationResult | null>(null);
  const [controls, setControls] = useState<RecommendationControls>(DEFAULT_RECOMMENDATION_CONTROLS);
  const [isLoadingRecommendation, setIsLoadingRecommendation] = useState(true);

  useEffect(() => {
    let isMounted = true;

    loadRecommendation(DEFAULT_RECOMMENDATION_CONTROLS, () => isMounted);

    return () => {
      isMounted = false;
    };
  }, []);

  async function loadRecommendation(nextControls = controls, shouldApply = () => true) {
    setIsLoadingRecommendation(true);

    try {
      const response = await fetch("/api/recommendations", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          context: {
            mood: nextControls.mood,
            purpose: nextControls.purpose,
            maxTravelMinutes: nextControls.maxTravelMinutes,
            preferredTags: parsePreferredTags(nextControls.preferredTagsText)
          },
          filters: {
            query: nextControls.query,
            openNowOnly: nextControls.openNowOnly
          },
          weights: {
            preference: nextControls.preferenceWeight
          }
        })
      });
      const data = (await response.json()) as RecommendationApiResponse;

      if (!shouldApply()) {
        return;
      }

      setContext(data.context);
      setRecommendation(data.recommendations[0] ?? null);
    } finally {
      if (shouldApply()) {
        setIsLoadingRecommendation(false);
      }
    }
  }

  return (
    <div className="prototype-shell">
      <div className="phone">
        <div className="phone-screen">
          {screen === "welcome" && <WelcomeScreen go={setScreen} />}
          {screen === "home" && (
            <HomeScreen
              go={setScreen}
              context={context}
              controls={controls}
              isLoading={isLoadingRecommendation}
              onApplyControls={() => loadRecommendation(controls)}
              onControlsChange={setControls}
              recommendation={recommendation}
            />
          )}
          {screen === "detail" && <DetailScreen go={setScreen} recommendation={recommendation} />}
          {screen === "plan" && <PlanScreen go={setScreen} recommendation={recommendation} />}
        </div>
      </div>
    </div>
  );
}

function parsePreferredTags(value: string) {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}
