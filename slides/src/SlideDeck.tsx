import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { FallingPattern } from "@/components/ui/falling-pattern";
import { cn } from "@/lib/utils";

export type Slide = {
  title: string;
  subtitle?: string;
  bullets?: string[];
};

const SLIDES: Slide[] = [
  {
    title: "Grafana & Datadog → Elastic Observability Serverless",
    subtitle: "Migration workshop deck",
    bullets: [
      "OTLP → managed mOTLP · logs-*, metrics-*, traces-*",
      "Two labs: 20 Grafana + 10 Datadog dashboards",
    ],
  },
  {
    title: "Telemetry path",
    bullets: [
      "Python OTLP fleet + Alloy :4317/:4318",
      "Prometheus scrape (Alloy self-metrics)",
      "Authorization: ApiKey → Elastic ingest endpoint",
    ],
  },
  {
    title: "Two-stage conversion to ES|QL",
    bullets: [
      "Stage 1: grafana_to_elastic.py / datadog_dashboard_to_elastic.py → draft JSON (PromQL or Datadog q preserved in migration.*)",
      "Stage 2: publish_grafana_drafts_kibana.py → Lens ES|QL + Dashboards API",
    ],
  },
  {
    title: "Classification → Lens",
    bullets: [
      "Regex categories: cpu, memory, http, latency, storage (disk proxies), k8s, …",
      "BUCKET(@timestamp, duration) — WORKSHOP_ESQL_BUCKET_DURATION",
      "Multi-series: breakdown by service.name",
    ],
  },
  {
    title: "Lab 1 — Grafana",
    bullets: [
      "Path A: migrate_grafana_dashboards_to_serverless.sh",
      "Path B: Cursor — export KIBANA_URL / ES_API_KEY, grafana_to_elastic + publish",
    ],
  },
  {
    title: "Lab 2 — Datadog",
    bullets: [
      "Path A: migrate_datadog_dashboards_to_serverless.sh",
      "12 widgets per DD dashboard · optional GRAFANA_IMPORT_FROM / ES app dashboards publisher",
    ],
  },
  {
    title: "Ops checklist",
    bullets: [
      "sync_workshop_from_git.sh · check_workshop_otel_pipeline.sh",
      "GitHub Pages: Actions deploy this slides/ app to /repo/",
    ],
  },
];

export function SlideDeck() {
  const [i, setI] = useState(0);
  const n = SLIDES.length;
  const slide = SLIDES[i];

  const prev = useCallback(() => setI((x) => (x <= 0 ? n - 1 : x - 1)), [n]);
  const next = useCallback(() => setI((x) => (x >= n - 1 ? 0 : x + 1)), [n]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") {
        e.preventDefault();
        next();
      }
      if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        prev();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, prev]);

  return (
    <div className="relative min-h-screen w-full overflow-hidden">
      <FallingPattern className="fixed inset-0 h-screen [mask-image:radial-gradient(ellipse_at_center,transparent_20%,var(--background)_75%)]" />

      <div className="relative z-10 flex min-h-screen flex-col">
        <header className="flex items-center justify-between border-b border-white/10 bg-black/20 px-4 py-3 backdrop-blur-sm">
          <span className="font-mono text-xs text-white/70">
            elastic-serverless-migration-lab
          </span>
          <span className="font-mono text-xs text-white/50">
            {i + 1} / {n}
          </span>
        </header>

        <main className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center">
          <h1 className="max-w-4xl font-mono text-3xl font-extrabold tracking-tight text-white drop-shadow-lg sm:text-5xl md:text-6xl">
            {slide.title}
          </h1>
          {slide.subtitle ? (
            <p className="mt-4 max-w-2xl text-lg text-white/80">{slide.subtitle}</p>
          ) : null}
          {slide.bullets?.length ? (
            <ul className="mt-10 max-w-2xl space-y-3 text-left text-base text-white/90 sm:text-lg">
              {slide.bullets.map((b) => (
                <li key={b} className="flex gap-3">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--primary)]" />
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </main>

        <footer className="flex items-center justify-center gap-4 border-t border-white/10 bg-black/30 px-4 py-4 backdrop-blur-md">
          <button
            type="button"
            onClick={prev}
            className="flex items-center gap-1 rounded-lg border border-white/20 bg-white/5 px-4 py-2 text-sm text-white transition hover:bg-white/10"
            aria-label="Previous slide"
          >
            <ChevronLeft className="size-4" />
            Prev
          </button>
          <div className="flex gap-1.5">
            {SLIDES.map((_, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => setI(idx)}
                className={cn(
                  "h-2 w-2 rounded-full transition",
                  idx === i ? "bg-[var(--primary)]" : "bg-white/30 hover:bg-white/50",
                )}
                aria-label={`Go to slide ${idx + 1}`}
              />
            ))}
          </div>
          <button
            type="button"
            onClick={next}
            className="flex items-center gap-1 rounded-lg border border-white/20 bg-white/5 px-4 py-2 text-sm text-white transition hover:bg-white/10"
            aria-label="Next slide"
          >
            Next
            <ChevronRight className="size-4" />
          </button>
        </footer>
      </div>
    </div>
  );
}
