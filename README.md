# NEXT-STOPS Clickable Prototype

A runnable Next.js UI prototype for the NEXT-STOPS "Calm Intelligence" design direction.

## Run locally

```bash
npm install
npm run dev
```

Open the local URL shown in your terminal.

## Prototype flow

Welcome → Home → Attraction Detail → Plan Your Visit → Home

Clickable areas:
- Welcome: Start discovering / Continue as guest
- Home: tap the large Next Stop card
- Detail: Plan this stop / Skip
- Plan: Add to today
- Bottom navigation: Home, Explore, Plan

## Figma prototype mapping

Create these frames:
1. Welcome
2. Home
3. Attraction Detail
4. Plan Your Visit

Interactions:
- Welcome primary button → Navigate to Home / Smart Animate / Ease out / 300ms
- Home Next Stop Card → Navigate to Attraction Detail / Smart Animate / Ease out / 300ms
- Detail Plan Button → Navigate to Plan Your Visit / Smart Animate / Ease out / 300ms
- Detail Skip Button → Navigate to Home / Instant or Dissolve / 200ms
- Plan Add Button → Navigate to Home / Smart Animate / Ease out / 300ms

Motion rule: soft fade + rise, never aggressive slide transitions.
