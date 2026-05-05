import { ArrowLeft, Bell, CalendarCheck, CloudSun, Compass, Footprints, Home, Leaf, Map, MapPinned, RefreshCw, Sparkles, UserRound } from "lucide-react";
import { AppIcon } from "./AppIcon";

export type Screen = "welcome" | "home" | "detail" | "plan";

export function PrimaryButton({ children, onClick, subtle = false }: { children: React.ReactNode; onClick?: () => void; subtle?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={subtle ? "h-12 rounded-full bg-white px-6 text-sm font-semibold text-indigo shadow-calm active:scale-[.98]" : "h-13 rounded-full soft-gradient px-6 py-3 text-sm font-semibold text-white shadow-float active:scale-[.98]"}
    >
      {children}
    </button>
  );
}

export function WelcomeScreen({ go }: { go: (s: Screen) => void }) {
  return (
    <main className="flex min-h-[816px] flex-col px-7 py-10">
      <div className="flex-1 pt-20 text-center">
        <div className="mx-auto mb-8 w-fit breathe"><AppIcon size={96} /></div>
        <p className="mb-3 text-xs font-bold tracking-[.28em] text-wellness">NEXT-STOPS</p>
        <h1 className="mx-auto max-w-[280px] text-4xl font-semibold tracking-[-.05em] text-ink">Not sure where to go next?</h1>
        <p className="mx-auto mt-5 max-w-[292px] text-[15px] leading-7 text-muted">We read your day, your energy, and the weather to gently suggest your next perfect stop.</p>
      </div>
      <div className="space-y-3 pb-4">
        <PrimaryButton onClick={() => go("home")}>Start discovering</PrimaryButton>
        <button onClick={() => go("home")} className="w-full text-sm font-medium text-muted">Continue as guest</button>
      </div>
    </main>
  );
}

function Nav({ current, go }: { current: Screen; go: (s: Screen) => void }) {
  const items = [
    ["home", Home, "Home"], ["detail", Compass, "Explore"], ["plan", CalendarCheck, "Plan"], ["home", UserRound, "You"]
  ] as const;
  return <div className="absolute bottom-5 left-5 right-5 flex justify-around rounded-[28px] bg-white/90 p-3 shadow-calm backdrop-blur">{items.map(([screen, Icon, label]) => <button key={label} onClick={() => go(screen)} className={current === screen ? "text-indigo" : "text-slate-400"}><Icon className="mx-auto h-5 w-5"/><span className="mt-1 block text-[10px] font-semibold">{label}</span></button>)}</div>;
}

export function HomeScreen({ go }: { go: (s: Screen) => void }) {
  return <main className="relative min-h-[816px] px-6 py-8 fade-up">
    <header className="mb-6 flex items-center justify-between"><div><p className="text-sm text-muted">Good morning, Ian</p><h2 className="text-3xl font-semibold tracking-[-.04em]">Where to next?</h2></div><button className="grid h-11 w-11 place-items-center rounded-full bg-white shadow-calm"><Bell className="h-5 w-5"/></button></header>
    <section onClick={() => go("detail")} className="cursor-pointer rounded-app bg-white p-5 shadow-calm transition active:scale-[.99]">
      <div className="mb-5 flex items-start justify-between"><p className="text-xs font-bold tracking-[.22em] text-indigo">YOUR NEXT STOP</p><Sparkles className="h-5 w-5 text-lavender"/></div>
      <div className="mb-5 h-32 rounded-[24px] bg-gradient-to-br from-mist via-white to-[#ECEBFF] p-4"><div className="h-full rounded-[22px] border border-white/70 bg-white/50"/></div>
      <h3 className="text-2xl font-semibold tracking-[-.03em]">Riverside Botanical Walk</h3>
      <p className="mt-2 text-sm leading-6 text-muted">Low crowd, soft weather, and a gentle 38-minute reset.</p>
      <div className="mt-5 flex gap-2"><Chip icon={<CloudSun/>} text="24°C"/><Chip icon={<Footprints/>} text="2.1 km"/><Chip icon={<Leaf/>} text="Calm"/></div>
    </section>
    <section className="mt-5 grid grid-cols-2 gap-3"><Metric title="Steps" value="3,240"/><Metric title="Energy" value="Gentle"/><Metric title="Rain" value="12%"/><Metric title="Mood" value="Reset"/></section>
    <Nav current="home" go={go}/>
  </main>;
}

function Chip({ icon, text }: { icon: React.ReactElement; text: string }) { return <span className="flex items-center gap-1 rounded-full border border-slate-100 bg-white px-3 py-2 text-xs font-semibold text-muted">{icon && <span className="[&>svg]:h-3.5 [&>svg]:w-3.5">{icon}</span>}{text}</span>; }
function Metric({ title, value }: { title: string; value: string }) { return <div className="rounded-[22px] bg-white p-4 shadow-calm"><p className="text-xs text-muted">{title}</p><p className="mt-1 text-lg font-semibold">{value}</p></div>; }

export function DetailScreen({ go }: { go: (s: Screen) => void }) {
  return <main className="min-h-[816px] px-6 py-8 fade-up"><button onClick={() => go("home")} className="mb-6 flex items-center gap-2 text-sm font-semibold text-muted"><ArrowLeft className="h-4 w-4"/>Back</button><div className="mb-6 h-56 rounded-[32px] bg-gradient-to-br from-[#E5F3EA] via-white to-[#EBE8FF] p-6 shadow-calm"><MapPinned className="h-8 w-8 text-indigo"/><div className="mt-14 h-2 w-48 rounded-full bg-white/80"/><div className="mt-3 h-2 w-32 rounded-full bg-white/70"/></div><p className="text-xs font-bold tracking-[.22em] text-indigo">MATCH SCORE 94%</p><h1 className="mt-2 text-3xl font-semibold tracking-[-.04em]">Riverside Botanical Walk</h1><p className="mt-3 text-[15px] leading-7 text-muted">Recommended because your activity is light today, the weather is mild, and this route gives you a relaxed outdoor reset without overload.</p><div className="mt-5 flex flex-wrap gap-2"><Chip icon={<CloudSun/>} text="Best now"/><Chip icon={<Footprints/>} text="38 min"/><Chip icon={<Leaf/>} text="Low crowd"/></div><div className="mt-7 space-y-3"><Reason text="Gentle temperature and low rain chance"/><Reason text="Close enough for a spontaneous stop"/><Reason text="Matches your calm preference pattern"/></div><div className="mt-7 flex gap-3"><PrimaryButton onClick={() => go("plan")}>Plan this stop</PrimaryButton><PrimaryButton subtle onClick={() => go("home")}><RefreshCw className="inline h-4 w-4"/> Skip</PrimaryButton></div></main>;
}
function Reason({ text }: { text: string }) { return <div className="rounded-2xl bg-white p-4 text-sm font-medium text-ink shadow-calm">{text}</div>; }

export function PlanScreen({ go }: { go: (s: Screen) => void }) {
  return <main className="min-h-[816px] px-6 py-8 fade-up"><button onClick={() => go("detail")} className="mb-6 flex items-center gap-2 text-sm font-semibold text-muted"><ArrowLeft className="h-4 w-4"/>Back</button><h1 className="text-3xl font-semibold tracking-[-.04em]">Plan your visit</h1><p className="mt-2 text-sm text-muted">A light route designed around your current day.</p><div className="mt-6 rounded-app bg-white p-5 shadow-calm"><div className="mb-4 flex items-center justify-between"><p className="font-semibold">Soft route</p><Map className="h-5 w-5 text-indigo"/></div><div className="h-44 rounded-[24px] bg-gradient-to-br from-mist to-[#EEECFF] p-5"><div className="h-full rounded-[22px] border-2 border-dashed border-white/90"/></div></div><div className="mt-5 space-y-3"><PlanItem title="Best time" detail="Within the next 90 minutes"/><PlanItem title="Bring" detail="Light jacket, water"/><PlanItem title="Weather" detail="Cloudy, comfortable, low rain"/><PlanItem title="Energy fit" detail="Low effort, high reset"/></div><div className="mt-7"><PrimaryButton onClick={() => go("home")}>Add to today</PrimaryButton></div></main>;
}
function PlanItem({ title, detail }: { title: string; detail: string }) { return <div className="flex items-center justify-between rounded-2xl bg-white p-4 shadow-calm"><span className="font-semibold">{title}</span><span className="text-right text-sm text-muted">{detail}</span></div>; }
