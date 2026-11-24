// RepoCrew metrics strip: four compact cards, all computed from the database.
import { Activity, CheckCircle2, Timer, Wrench } from "lucide-react";
import type { Metrics } from "../types";

export default function MetricsStrip({ metrics }: { metrics: Metrics | null }) {
  const items = [
    {
      label: "Issues processed",
      value: metrics ? String(metrics.issues_processed) : "—",
      icon: <Wrench size={14} className="text-accent" />,
    },
    {
      label: "Patches approved",
      value: metrics ? String(metrics.patches_approved) : "—",
      icon: <CheckCircle2 size={14} className="text-success" />,
    },
    {
      label: "Test pass rate",
      value: metrics ? `${Math.round(metrics.test_pass_rate * 100)}%` : "—",
      icon: <Activity size={14} className="text-violet" />,
    },
    {
      label: "Avg run time",
      value: metrics ? `${metrics.avg_run_time_seconds.toFixed(1)}s` : "—",
      icon: <Timer size={14} className="text-warning" />,
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="card flex items-center gap-3 px-4 py-3">
          <div className="rounded-lg border border-line bg-raised/70 p-2">{item.icon}</div>
          <div>
            <div className="text-lg font-bold leading-5">{item.value}</div>
            <div className="text-[11px] font-medium text-muted">{item.label}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
