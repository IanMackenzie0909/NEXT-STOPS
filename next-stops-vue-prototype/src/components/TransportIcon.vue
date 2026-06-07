<script setup>
import bikeIcon from "../assets/transport/bike.png";
import busIcon from "../assets/transport/bus.png";
import carIcon from "../assets/transport/car.png";
import metroIcon from "../assets/transport/metro.png";
import scooterIcon from "../assets/transport/scooter.png";
import walkIcon from "../assets/transport/walk.png";

const props = defineProps({
  name: { type: String, default: "" },
  label: { type: String, default: "" },
});

const icons = {
  bicycle: bikeIcon,
  bike: bikeIcon,
  bus: busIcon,
  car: carIcon,
  train: metroIcon,
  metro: metroIcon,
  mrt: metroIcon,
  scooter: scooterIcon,
  motorcycle: scooterIcon,
  walk: walkIcon,
  walking: walkIcon,
};

function resolveIcon() {
  const key = String(props.name || "").toLowerCase();
  if (icons[key]) return icons[key];
  const text = `${props.name || ""} ${props.label || ""}`.toLowerCase();
  if (/bicycle|bike|腳踏車|自行車/.test(text)) return bikeIcon;
  if (/motor|scooter|機車/.test(text)) return scooterIcon;
  if (/bus|公車/.test(text)) return busIcon;
  if (/mrt|metro|捷運|rail|train|火車|大眾/.test(text)) return metroIcon;
  if (/walk|步行|走路/.test(text)) return walkIcon;
  return carIcon;
}
</script>

<template>
  <img class="transport-icon-img" :src="resolveIcon()" alt="" aria-hidden="true" />
</template>
