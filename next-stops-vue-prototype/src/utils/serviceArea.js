import { SERVICE_AREA_LABEL, SERVICE_AREA_NOTICE } from "../constants";
import serviceArea from "../data/service-area-shuangbei.json";

function pointInRing(lat, lon, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersects = ((yi > lat) !== (yj > lat))
      && (lon < ((xj - xi) * (lat - yi)) / ((yj - yi) || Number.EPSILON) + xi);
    if (intersects) inside = !inside;
  }
  return inside;
}

function pointInPolygon(lat, lon, polygon) {
  if (!Array.isArray(polygon) || !polygon.length || !pointInRing(lat, lon, polygon[0])) return false;
  return !polygon.slice(1).some((hole) => pointInRing(lat, lon, hole));
}

export function findServiceArea(lat, lon) {
  const latitude = Number(lat);
  const longitude = Number(lon);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  return serviceArea.features.find((feature) => (
    feature.polygons.some((polygon) => pointInPolygon(latitude, longitude, polygon))
  )) || null;
}

export function isWithinServiceArea(lat, lon) {
  return Boolean(findServiceArea(lat, lon));
}

export function serviceAreaError(source = "current") {
  const title = source === "favorite" ? "常用起點不在服務範圍內" : "目前定位不在服務範圍內";
  return {
    tone: "warning",
    title,
    message: SERVICE_AREA_NOTICE,
    meta: `服務範圍：${SERVICE_AREA_LABEL}`,
  };
}
