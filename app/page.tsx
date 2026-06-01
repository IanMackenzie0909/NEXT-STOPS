"use client";

import { useEffect, useState } from "react";
import { DetailScreen, HomeScreen, PlanScreen, Screen, WelcomeScreen } from "../components/ui";
import type { RecommendationContext, RecommendationResult } from "../lib/recommendation-engine";

type RecommendationApiResponse = {
  context: RecommendationContext;
  recommendations: RecommendationResult[];
};

export default function Page() {
  const [screen, setScreen] = useState<Screen>("welcome");
  const [context, setContext] = useState<RecommendationContext | null>(null);
  const [recommendation, setRecommendation] = useState<RecommendationResult | null>(null);
  const [isLoadingRecommendation, setIsLoadingRecommendation] = useState(true);

  useEffect(() => {
    let isMounted = true;

    async function loadRecommendation() {
      try {
        const response = await fetch("/api/recommendations");
        const data = (await response.json()) as RecommendationApiResponse;

        if (!isMounted) {
          return;
        }

        setContext(data.context);
        setRecommendation(data.recommendations[0] ?? null);
      } finally {
        if (isMounted) {
          setIsLoadingRecommendation(false);
        }
      }
    }

    loadRecommendation();

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <div className="prototype-shell">
      <div className="phone">
        <div className="phone-screen">
          {screen === "welcome" && <WelcomeScreen go={setScreen} />}
          {screen === "home" && <HomeScreen go={setScreen} context={context} isLoading={isLoadingRecommendation} recommendation={recommendation} />}
          {screen === "detail" && <DetailScreen go={setScreen} recommendation={recommendation} />}
          {screen === "plan" && <PlanScreen go={setScreen} recommendation={recommendation} />}
        </div>
      </div>
    </div>
  );
}
