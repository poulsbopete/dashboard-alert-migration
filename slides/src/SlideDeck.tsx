import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { FallingPattern } from "@/components/ui/falling-pattern";
import { cn } from "@/lib/utils";

export type StatCard = {
  /** Big figure (e.g. 4–10×, 30, 2) */
  figure: string;
  title: string;
  caption?: string;
};

export type Slide = {
  title: string;
  subtitle?: string;
  bullets?: string[];
  /** Elastic-by-the-numbers style grid */
  statCards?: StatCard[];
  /** Instruqt (or other) lab — opens in a new browser tab */
  workshopUrl?: string;
  workshopLinkLabel?: string;
  /**
   * File in `slides/public/` (copied to site root). Use with Git LFS for large MP4s.
   * URL respects Vite `base` (GitHub Pages project path).
   */
  videoSrc?: string;
};

const INSTRUQT_INVITE = "https://play.instruqt.com/elastic/invite/fmt96ftdm41w";

/** Upstream repos for the Instruqt labs — open issues & PRs here (migration CLI + YAML compiler). */
const UPSTREAM_REPOS: {
  label: string;
  repoUrl: string;
  issuesUrl: string;
  pullsUrl: string;
  note?: string;
}[] = [
  {
    label: "elastic/mig-to-kbn",
    repoUrl: "https://github.com/elastic/mig-to-kbn",
    issuesUrl: "https://github.com/elastic/mig-to-kbn/issues",
    pullsUrl: "https://github.com/elastic/mig-to-kbn/pulls",
    note: "Grafana & Datadog → Kibana migration (`grafana-migrate`, `datadog-migrate`).",
  },
  {
    label: "strawgate/kb-yaml-to-lens",
    repoUrl: "https://github.com/strawgate/kb-yaml-to-lens",
    issuesUrl: "https://github.com/strawgate/kb-yaml-to-lens/issues",
    pullsUrl: "https://github.com/strawgate/kb-yaml-to-lens/pulls",
    note: "kb-dashboard-cli — YAML dashboards → Kibana NDJSON (used by mig-to-kbn compile).",
  },
];

const SLIDES: Slide[] = [
  {
    title: "Workshop walkthrough",
    subtitle:
      "Quick tour of the Instruqt lab — Grafana & Datadog dashboards and alerts toward Elastic Observability Serverless.",
    videoSrc: "dashboard-alert-migration.mp4",
  },
  {
    title: "Try the guided experience",
    subtitle:
      "Walk through a realistic Grafana and Datadog → Elastic Observability Serverless migration in a browser sandbox — no install required.",
    workshopUrl: INSTRUQT_INVITE,
    workshopLinkLabel: "Launch Elastic sandbox (Instruqt)",
  },
  {
    title: "Why teams re-home Grafana & Datadog on Elastic",
    subtitle:
      "Customers want fewer silos between metrics stores, log pipelines, and APM — without re-authoring years of dashboards from a blank canvas.",
    bullets: [
      "One managed stack for logs, metrics, and traces (Elastic Observability) instead of bolting together separate vendors and query languages.",
      "OpenTelemetry-native ingest fits how you already ship telemetry — including dual-publish or gradual cutover from existing collectors.",
      "ES|QL and Lens give analysts one executable language across signals, with Kibana as a single operations and executive surface.",
      "APIs and automation matter at enterprise scale: dashboards and alerting should be versionable, repeatable, and CI-friendly — not only UI clicks.",
    ],
  },
  {
    title: "What this story demonstrates",
    subtitle:
      "A credible slice of a real migration: representative Grafana and Datadog assets land as reviewable Kibana content on Serverless.",
    bullets: [
      "A multi-service OTLP footprint — the same pattern customers use when standardizing on Elastic managed ingest.",
      "Dozens of Grafana-style and Datadog-style dashboards exercised end-to-end so you can stress-test classification, ES|QL, and stakeholder review.",
      "Alert artifacts travel the same automation spine as dashboards — drafts first, then human approval before production enforcement.",
      "Everything you see is reproducible from source exports + automation — the same ingredients you would pipeline internally.",
    ],
  },
  {
    title: "Elastic by the numbers",
    subtitle:
      "Directional benefits we use in customer business cases — your timelines depend on panel complexity, security reviews, and cutover windows.",
    statCards: [
      {
        figure: "4–10×",
        title: "Less manual dashboard work",
        caption:
          "Planning teams often see this range when bulk conversion plus Dashboards API publish replaces hand-rebuilding every visualization from scratch.",
      },
      {
        figure: "30",
        title: "Dashboards in this journey",
        caption:
          "Twenty Grafana-style and ten Datadog-style boards — enough volume to prove classification, not just a happy-path demo.",
      },
      {
        figure: "2",
        title: "Controlled phases",
        caption:
          "Phase 1: preserve source intent in structured drafts (PromQL, Datadog queries). Phase 2: publish executable ES|QL in Lens via API.",
      },
      {
        figure: "Hours",
        title: "Time to a reviewable wave",
        caption:
          "Many waves that once consumed analyst-days compress to scripted runs, validation, and SME sign-off — then rerun as you tune mappings.",
      },
      {
        figure: "1",
        title: "Unified ingest plane",
        caption:
          "One OTLP-oriented path for logs, metrics, and traces — fewer parallel integrations while you sunset legacy backends.",
      },
      {
        figure: "4",
        title: "Sample alert definitions",
        caption:
          "Representative Datadog monitor-style JSON becomes Kibana rule drafts — the same governance model as migrated dashboards.",
      },
    ],
  },
  {
    title: "Your telemetry, Elastic’s managed pipeline",
    subtitle:
      "Elastic Observability Serverless speaks OTLP fluently — the open standard teams already adopt alongside Grafana and Datadog agents.",
    bullets: [
      "Collectors and agents forward gRPC/HTTP OTLP; Elastic managed ingest terminates with sensible defaults for production cardinality.",
      "Prometheus-compatible scrape still fits sidecars and service meshes — Elastic becomes the sink, not another siloed Prometheus clone.",
      "Scoped API keys and Org security align with how enterprises govern cross-team observability projects.",
      "In the guided sandbox, live telemetry confirms Lens and Discover against real series — not screenshots.",
    ],
  },
  {
    title: "A deliberate two-stage migration",
    subtitle:
      "Reduce risk: separate “capture legacy intent” from “publish executable analytics” so auditors and SREs stay aligned.",
    bullets: [
      "Stage 1 — Ingest source-of-truth exports (Grafana JSON, Datadog dashboards/monitors) and emit Elastic-oriented drafts with traceable metadata.",
      "Stage 2 — Publish Lens panels and rules through Kibana APIs, with ES|QL grounded in your actual indices and naming conventions.",
      "Original PromQL and Datadog queries remain referenced for transparency — they are not silently reinterpreted inside Elasticsearch.",
      "Rerun, diff, and promote the same assets through dev → staging → prod — matching how mature platform teams ship change.",
    ],
  },
  {
    title: "From familiar signals to Lens charts",
    subtitle:
      "Automation classifies the themes SREs already watch — CPU, latency, HTTP health, Kubernetes signals — then maps them to durable ES|QL.",
    bullets: [
      "Pattern recognition groups panels so HTTP saturation, golden signals, and infrastructure proxies land in the right Lens templates.",
      "Time bucketing follows your duration policy so charts honor SLO windows instead of arbitrary fixed buckets.",
      "Breakdowns favor dimensions you already standardized — for example service.name — so migrated boards stay comparable week over week.",
      "Edge cases become explicit in documentation panels: humans refine ES|QL where automation should not guess.",
    ],
  },
  {
    title: "If you are a Grafana customer today",
    subtitle:
      "Classic JSON exports, Grafana Cloud app exports, and Elasticsearch-backed app panels each have a path — preserve dashboard IP as you move runtimes.",
    bullets: [
      "Bulk dashboard JSON: PromQL stays documented while Lens runs ES|QL against your Elastic data plane — no secret translation black box.",
      "Kubernetes-hosted Grafana with Elasticsearch datasources can pivot through the same publishing APIs your platform team already automates.",
      "Operating model: platform SREs run conversion and publish jobs; application owners validate visuals against golden datasets.",
      "Hands-on sandbox mirrors scripted paths your services team can lift into Jenkins, GitHub Actions, or internal runbooks.",
    ],
  },
  {
    title: "If you are a Datadog customer today",
    subtitle:
      "Dashboard JSON and monitor definitions are assets — ship the same discipline you use for IaC so Elastic inherits governance, not chaos.",
    bullets: [
      "Timeseries, top lists, and query widgets become Lens panels with Datadog q captured for audit — ES|QL is what runs at query time.",
      "Monitors surface as Kibana alert drafts so SecOps and SREs approve thresholds, connectors, and runbooks before go-live.",
      "Tag-heavy APM and host maps align with OTLP resource attributes already landing in Elastic — fewer semantic rewrites mid-migration.",
      "Dense dashboards prove the classification engine: many widgets per board is closer to customer reality than toy samples.",
    ],
  },
  {
    title: "Your next steps with Elastic",
    subtitle:
      "Treat the sandbox as a rehearsal: the same checklist scales to your first production wave once connectivity and roles are ready.",
    bullets: [
      "Validate ingest: Confirm logs, metrics, and traces you care about appear in Elastic with the tags and services your teams expect.",
      "Review migrated drafts with dashboard owners: titles, ES|QL, and annotations should pass a human gate before executives rely on them.",
      "Exercise alerting: Wire notification destinations you already trust, run failure drills, and only then broaden enforcement.",
      "Industrialize: Check automation into source control, parameterize environments, and schedule the next portfolio slice — volume wins when repeatability wins.",
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
      {/* Full pattern (no CSS mask — masks often drop the whole layer cross-browser). Legibility: content card below. */}
      <FallingPattern className="fixed inset-0 z-0 h-screen" />

      <div className="relative z-10 flex min-h-screen flex-col">
        <header className="flex items-center justify-between border-b border-white/10 bg-black/20 px-4 py-3 backdrop-blur-sm">
          <span className="font-mono text-xs text-white/70">
            Grafana & Datadog → Elastic Observability
          </span>
          <span className="font-mono text-xs text-white/50">
            {i + 1} / {n}
          </span>
        </header>

        <main className="flex flex-1 flex-col items-center justify-center px-4 py-10 text-center sm:px-6">
          <div
            className={cn(
              "w-full rounded-2xl px-6 py-8 md:px-10 md:py-12",
              "border border-white/15 bg-zinc-950/85 shadow-2xl backdrop-blur-md",
              "ring-1 ring-black/40",
              slide.statCards?.length ? "max-w-6xl" : slide.videoSrc ? "max-w-5xl" : "max-w-4xl",
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
              <p className="mx-auto mt-4 max-w-3xl text-lg text-zinc-200/95">{slide.subtitle}</p>
            ) : null}
            {slide.videoSrc ? (
              <div className="mt-8 w-full">
                <video
                  className="mx-auto w-full max-h-[min(60vh,720px)] rounded-xl border border-white/15 bg-black/70 shadow-xl"
                  controls
                  playsInline
                  preload="metadata"
                  aria-label="Workshop overview video"
                >
                  <source
                    src={`${import.meta.env.BASE_URL}${slide.videoSrc}`}
                    type="video/mp4"
                  />
                  Your browser does not support embedded video — open the MP4 from the repository{" "}
                  <code className="rounded bg-white/10 px-1 text-sm">slides/public/</code> or run the lab in Instruqt.
                </video>
              </div>
            ) : null}
            {slide.statCards?.length ? (
              <div className="mt-10 grid w-full gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {slide.statCards.map((s) => (
                  <div
                    key={s.title}
                    className={cn(
                      "flex flex-col rounded-xl border border-[var(--primary)]/25 bg-gradient-to-br from-zinc-900/90 to-zinc-950/90",
                      "px-5 py-5 text-left shadow-lg ring-1 ring-white/5",
                    )}
                  >
                    <p
                      className={cn(
                        "font-mono text-4xl font-extrabold tracking-tight text-[var(--primary)] md:text-5xl",
                        "[text-shadow:0_0_40px_color-mix(in_oklab,var(--primary)_35%,transparent)]",
                      )}
                    >
                      {s.figure}
                    </p>
                    <p className="mt-3 font-mono text-sm font-semibold uppercase tracking-wide text-zinc-200">
                      {s.title}
                    </p>
                    {s.caption ? (
                      <p className="mt-2 text-sm leading-snug text-zinc-400">{s.caption}</p>
                    ) : null}
                  </div>
                ))}
              </div>
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
              <ul className="mx-auto mt-10 max-w-3xl space-y-3 text-left text-base text-zinc-100 sm:text-lg">
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

        <footer className="border-t border-white/10 bg-black/30 px-4 py-4 backdrop-blur-md">
          <div className="mx-auto flex max-w-4xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <div className="flex items-center justify-center gap-4 sm:justify-start">
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
            </div>
            <div className="text-center font-mono text-[10px] leading-relaxed text-zinc-500 sm:max-w-md sm:text-left sm:text-xs">
              <p className="text-zinc-400">
                Upstream feedback — <span className="text-zinc-300">Subham</span> and team ship the migration
                stack in{" "}
                <a
                  href={UPSTREAM_REPOS[0].repoUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--primary)] underline decoration-white/20 underline-offset-2 hover:decoration-[var(--primary)]"
                >
                  {UPSTREAM_REPOS[0].label}
                </a>
                ; open{" "}
                <a
                  href={UPSTREAM_REPOS[0].issuesUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--primary)] underline decoration-white/20 underline-offset-2 hover:decoration-[var(--primary)]"
                >
                  Issues
                </a>{" "}
                or{" "}
                <a
                  href={UPSTREAM_REPOS[0].pullsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--primary)] underline decoration-white/20 underline-offset-2 hover:decoration-[var(--primary)]"
                >
                  PRs
                </a>
                . Compiler:{" "}
                <a
                  href={UPSTREAM_REPOS[1].repoUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--primary)] underline decoration-white/20 underline-offset-2 hover:decoration-[var(--primary)]"
                >
                  {UPSTREAM_REPOS[1].label}
                </a>{" "}
                (
                <a
                  href={UPSTREAM_REPOS[1].issuesUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--primary)] underline decoration-white/20 underline-offset-2 hover:decoration-[var(--primary)]"
                >
                  Issues
                </a>
                ,{" "}
                <a
                  href={UPSTREAM_REPOS[1].pullsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--primary)] underline decoration-white/20 underline-offset-2 hover:decoration-[var(--primary)]"
                >
                  PRs
                </a>
                ).
              </p>
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
