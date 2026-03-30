import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { FallingPattern } from "@/components/ui/falling-pattern";
import { cn } from "@/lib/utils";

export type Slide = {
  title: string;
  subtitle?: string;
  bullets?: string[];
  /** Instruqt (or other) lab — opens in a new browser tab */
  workshopUrl?: string;
  workshopLinkLabel?: string;
};

const INSTRUQT_INVITE = "https://play.instruqt.com/elastic/invite/fmt96ftdm41w";

const SLIDES: Slide[] = [
  {
    title: "Start the Instruqt workshop",
    subtitle:
      "Open the Elastic sandbox in a new window. Leave these slides open to follow along with the labs.",
    workshopUrl: INSTRUQT_INVITE,
    workshopLinkLabel: "Open Instruqt invite",
  },
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
      <FallingPattern className="fixed inset-0 h-screen [mask-image:radial-gradient(ellipse_at_center,transparent_42%,white_78%)]" />

      <div className="relative z-10 flex min-h-screen flex-col">
        <header className="flex items-center justify-between border-b border-white/10 bg-black/20 px-4 py-3 backdrop-blur-sm">
          <span className="font-mono text-xs text-white/70">
            elastic-serverless-migration-lab
          </span>
          <span className="font-mono text-xs text-white/50">
            {i + 1} / {n}
          </span>
        </header>

        <main className="flex flex-1 flex-col items-center justify-center px-4 py-10 text-center sm:px-6">
          <div
            className={cn(
              "max-w-4xl rounded-2xl px-6 py-8 md:px-10 md:py-12",
              "border border-white/15 bg-zinc-950/85 shadow-2xl backdrop-blur-md",
              "ring-1 ring-black/40",
            )}
          >
            <h1
              className={cn(
                "max-w-4xl font-mono text-3xl font-extrabold tracking-tight sm:text-5xl md:text-6xl",
                "text-zinc-50 [text-shadow:0_2px_24px_rgba(0,0,0,0.85)]",
              )}
            >
              {slide.title}
            </h1>
            {slide.subtitle ? (
              <p className="mt-4 max-w-2xl text-lg text-zinc-200/95">{slide.subtitle}</p>
            ) : null}
            {slide.workshopUrl ? (
              <div className="mt-8 flex flex-col items-center gap-2">
                <a
                  href={slide.workshopUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={cn(
                    "inline-flex items-center justify-center gap-2 rounded-xl px-6 py-3.5",
                    "bg-[var(--primary)] font-mono text-sm font-semibold text-white shadow-lg",
                    "ring-1 ring-white/20 transition hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950",
                  )}
                  aria-label={`${slide.workshopLinkLabel ?? "Open workshop"} (opens in new tab)`}
                >
                  <ExternalLink className="size-4 shrink-0 opacity-90" aria-hidden />
                  {slide.workshopLinkLabel ?? "Open workshop"}
                </a>
                <span className="font-mono text-xs text-zinc-500">Opens in a new tab</span>
              </div>
            ) : null}
            {slide.bullets?.length ? (
              <ul className="mt-10 max-w-2xl space-y-3 text-left text-base text-zinc-100 sm:text-lg">
                {slide.bullets.map((b) => (
                  <li key={b} className="flex gap-3 leading-snug">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--primary)]" />
                    <span className="[text-shadow:0_1px_8px_rgba(0,0,0,0.85)]">{b}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
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
