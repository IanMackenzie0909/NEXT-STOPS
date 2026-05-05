export function AppIcon({ size = 72 }: { size?: number }) {
  return (
    <div
      className="relative grid place-items-center rounded-[24%] soft-gradient shadow-float"
      style={{ width: size, height: size }}
      aria-label="NEXT-STOPS app icon"
    >
      <div className="absolute inset-0 rounded-[24%] bg-white/10" />
      <div className="relative h-[42%] w-[56%] rounded-2xl bg-white shadow-calm rotate-[-7deg]">
        <div className="absolute left-3 top-3 h-2 w-14 rounded-full bg-indigo/20" />
        <div className="absolute bottom-3 left-3 h-2 w-9 rounded-full bg-wellness/70" />
      </div>
      <div className="absolute right-[23%] top-[22%] h-3 w-3 rounded-full bg-white shadow-[0_0_18px_rgba(255,255,255,.95)]" />
    </div>
  );
}
