import { useState } from "react";

// Single-hue magnitude bar chart (one metric per category, e.g. per-agent
// call counts) — sequential blue per the dataviz skill's default palette,
// no legend needed since color doesn't carry identity here (the x-axis
// label does). Thin bars (<=24px), 4px rounded data-end, value at the cap,
// hairline baseline, hover tooltip. No new chart-library dependency.
export default function BarChart({
  title,
  data,
  valueFormatter = (v: number) => v.toLocaleString(),
}: {
  title: string;
  data: { label: string; value: number }[];
  valueFormatter?: (v: number) => string;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const width = 480;
  const height = 180;
  const barWidth = Math.min(24, (width / Math.max(data.length, 1)) * 0.5);
  const slotWidth = width / Math.max(data.length, 1);
  const max = Math.max(1, ...data.map((d) => d.value));
  const baselineY = height - 24;

  return (
    <div className="viz-root">
      <h4 className="chart-title">{title}</h4>
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        <line x1={0} y1={baselineY} x2={width} y2={baselineY} className="chart-baseline" />
        {data.map((d, i) => {
          const barHeight = max > 0 ? (d.value / max) * (baselineY - 24) : 0;
          const slotCenter = slotWidth * i + slotWidth / 2;
          const x = slotCenter - barWidth / 2;
          const y = baselineY - barHeight;
          return (
            <g
              key={d.label}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
            >
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={Math.max(barHeight, 1)}
                rx={4}
                className="chart-bar"
                opacity={hovered === null || hovered === i ? 1 : 0.55}
              />
              <text x={x + barWidth / 2} y={y - 6} textAnchor="middle" className="chart-value-label">
                {valueFormatter(d.value)}
              </text>
              <text x={x + barWidth / 2} y={baselineY + 16} textAnchor="middle" className="chart-axis-label">
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
