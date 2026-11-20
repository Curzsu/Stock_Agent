type LogicalRange = { from: number; to: number };

export function constrainRange(range: LogicalRange, count: number): LogicalRange {
  const span = Math.min(range.to - range.from, count);
  const to = Math.min(count - 0.5, Math.max(span - 0.5, range.to));
  return { from: to - span, to };
}

export function zoomFromRight(range: LogicalRange, delta: number, count: number): LogicalRange {
  const factor = Math.exp(Math.max(-400, Math.min(delta, 400)) * 0.001);
  const span = Math.max(Math.min(2, count), (range.to - range.from) * factor);
  return constrainRange({ from: Math.max(-0.5, range.to - span), to: range.to }, count);
}
