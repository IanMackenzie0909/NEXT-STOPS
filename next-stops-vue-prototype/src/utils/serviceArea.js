import { SERVICE_AREA_LABEL, SERVICE_AREA_NOTICE } from "../constants";

const SHUANGBEI_POLYGON = [
  [121.3500, 25.1800],
  [121.2850, 25.1050],
  [121.3150, 25.0100],
  [121.3800, 24.8800],
  [121.5200, 24.7350],
  [121.7100, 24.8100],
  [121.9300, 24.9300],
  [122.0100, 25.0300],
  [121.9400, 25.1450],
  [121.7450, 25.3050],
  [121.4850, 25.3000],
];

const KEELUNG_EXCLUSION_POLYGON = [
  [121.6250, 25.0700],
  [121.8150, 25.0700],
  [121.8550, 25.1750],
  [121.7750, 25.2150],
  [121.6250, 25.1700],
];

function pointInPolygon(lat, lon, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0];
    const yi = polygon[i][1];
    const xj = polygon[j][0];
    const yj = polygon[j][1];
    const intersects = ((yi > lat) !== (yj > lat))
      && (lon < ((xj - xi) * (lat - yi)) / ((yj - yi) || Number.EPSILON) + xi);
    if (intersects) inside = !inside;
  }
  return inside;
}

export function isWithinServiceArea(lat, lon) {
  const latitude = Number(lat);
  const longitude = Number(lon);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return false;
  return pointInPolygon(latitude, longitude, SHUANGBEI_POLYGON)
    && !pointInPolygon(latitude, longitude, KEELUNG_EXCLUSION_POLYGON);
}

export function serviceAreaError(source = "current") {
  const title = source === "favorite" ? "常用起點不在服務區域內" : "目前定位不在服務區域內";
  return {
    tone: "warning",
    title,
    message: SERVICE_AREA_NOTICE,
    meta: `服務區域：${SERVICE_AREA_LABEL}`,
  };
}
