export default function StatTile({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="stat-tile">
      <div className="stat-tile-label">{label}</div>
      <div className="stat-tile-value">{value}</div>
    </div>
  );
}
