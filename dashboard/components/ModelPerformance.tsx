"use client";

import { useEffect, useState } from "react";
import { BarChart3, ImageOff } from "lucide-react";
import { getModelPerformance, getModelPerformancePlotUrl } from "@/lib/api";

interface PerformancePlot {
  filename: string;
  title: string;
}

export default function ModelPerformance() {
  const [plots, setPlots] = useState<PerformancePlot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getModelPerformance()
      .then((data) => {
        setPlots(Array.isArray(data.plots) ? data.plots : []);
        setError(null);
      })
      .catch((err) => {
        console.error("Failed to load model performance", err);
        setError("Could not load model evaluation plots");
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex-1 overflow-auto p-6" style={{ background: "var(--bg-primary)" }}>
      <div className="mb-6">
        <h1 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
          Model Performance
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
          Evaluation artifacts from docs/evaluation/eval
        </p>
      </div>

      {error && (
        <div className="panel mb-4">
          <div className="panel-body text-sm" style={{ color: "var(--warning)" }}>
            {error}
          </div>
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((item) => (
            <div key={item} className="panel animate-pulse h-80" />
          ))}
        </div>
      ) : plots.length === 0 ? (
        <div className="panel">
          <div className="panel-body flex items-center gap-3" style={{ color: "var(--text-muted)" }}>
            <ImageOff className="w-4 h-4" />
            No evaluation plots found.
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {plots.map((plot) => (
            <div key={plot.filename} className="panel">
              <div className="panel-header">
                <div className="flex items-center gap-2">
                  <BarChart3 className="w-4 h-4" style={{ color: "var(--accent)" }} />
                  <span className="panel-title">{plot.title}</span>
                </div>
                <span className="data-label">{plot.filename}</span>
              </div>
              <div className="panel-body">
                <img
                  src={getModelPerformancePlotUrl(plot.filename)}
                  alt={plot.title}
                  className="w-full rounded-md"
                  style={{ background: "white", border: "1px solid var(--border)" }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
