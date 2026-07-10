import { useState } from "react";

interface Point {
  x: string; // already-formatted label (e.g. date)
  y: number;
}

// Single-series magnitude-over-time line — sequential blue, 2px line,
// round join/cap, >=8px markers with a surface ring, hover tooltip. A
// single series needs no legend box (the title already names it) per the
// dataviz skill's own rule.
export default function TrendLineChart({
  title,
  points,
  valueFormatter = (v: number) => v.toFixed(2),
}: {
  title: string;
  points: Point[];
  valueFormatter?: (v: number) => string;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const width = 480;
  const height = 200;
  const padding = { top: 16, right: 16, bottom: 32, left: 16 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  if (points.length === 0) {
    return (
      <div className="viz-root">
        <h4 className="chart-title">{title}</h4>
        <p className="muted">No completed scans yet.</p>
      </div>
    );
  }

  const maxY = Math.max(1, ...points.map((p) => p.y));
  const stepX = points.length > 1 ? plotWidth / (points.length - 1) : 0;
  const coords = points.map((p, i) => ({
    x: padding.left + (points.length > 1 ? i * stepX : plotWidth / 2),
    y: padding.top + plotHeight - (p.y / maxY) * plotHeight,
  }));
  const path = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x},${c.y}`).join(" ");
  const baselineY = padding.top + plotHeight;

  return (
    <div className="viz-root">
      <h4 className="chart-title">{title}</h4>
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        <line x1={padding.left} y1={baselineY} x2={width - padding.right} y2={baselineY} className="chart-baseline" />
        <path d={path} className="chart-line" fill="none" />
        {coords.map((c, i) => (
          <g key={i} onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)}>
            <circle cx={c.x} cy={c.y} r={7} className="chart-marker-ring" />
            <circle cx={c.x} cy={c.y} r={5} className="chart-marker" />
            {hovered === i && (
              <g>
                <rect x={c.x - 34} y={c.y - 34} width={68} height={20} rx={4} className="chart-tooltip-bg" />
                <text x={c.x} y={c.y - 20} textAnchor="middle" className="chart-tooltip-text">
                  {valueFormatter(points[i].y)}
                </text>
              </g>
            )}
          </g>
        ))}
        {/* Sparing direct labels: first and last point only, per "label
            the endpoint, the extreme" — not every point. */}
        <text x={coords[0].x} y={baselineY + 16} textAnchor="start" className="chart-axis-label">
          {points[0].x}
        </text>
        {points.length > 1 && (
          <text x={coords[coords.length - 1].x} y={baselineY + 16} textAnchor="end" className="chart-axis-label">
            {points[points.length - 1].x}
          </text>
        )}
      </svg>
    </div>
  );
}
