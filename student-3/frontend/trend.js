/** Missing observations break a line; they must not imply a continuous recorded trend. */
export function trendPath(items, months, x, y) {
  const observations = new Map(items.map((item) => [item.month, item.value]));
  let connected = false;
  const segments = [];
  months.forEach((month, index) => {
    const value = observations.get(month);
    if (!Number.isFinite(value)) { connected = false; return; }
    segments.push(`${connected ? "L" : "M"}${x(index)},${y(value)}`);
    connected = true;
  });
  return segments.join(" ");
}
