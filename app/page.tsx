"use client";

import { useState } from "react";
import { DetailScreen, HomeScreen, PlanScreen, Screen, WelcomeScreen } from "../components/ui";

export default function Page() {
  const [screen, setScreen] = useState<Screen>("welcome");

  return (
    <div className="prototype-shell">
      <div className="phone">
        <div className="phone-screen">
          {screen === "welcome" && <WelcomeScreen go={setScreen} />}
          {screen === "home" && <HomeScreen go={setScreen} />}
          {screen === "detail" && <DetailScreen go={setScreen} />}
          {screen === "plan" && <PlanScreen go={setScreen} />}
        </div>
      </div>
    </div>
  );
}
