import type { AppState } from "./types";

const W = 300;
const H = 110;
const LOW_LINE = 70;

/** Last 3 h of readings (thin, dimmed) + the forecast mean (dotted) and band (faint). */
export function Sparkline({ state }: { state: AppState }) {
  const hist = state.history;
  if (hist.length < 2) return null;
  const now = Date.parse(state.now);
  const fc = state.forecast;
  const t0 = now - 3 * 3600e3;
  const t1 = now + 30 * 60e3;
  const vals = hist.map((p) => p.mgdl).concat(fc ? [...fc.lo, ...fc.hi] : []);
  const lo = Math.min(55, ...vals);
  const hi = Math.max(200, ...vals);
  const X = (t: number) => ((t - t0) / (t1 - t0)) * W;
  const Y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
  const line = hist.map((p) => `${X(Date.parse(p.t)).toFixed(1)},${Y(p.mgdl).toFixed(1)}`).join(" ");

  let band = "";
  let fcLine = "";
  if (fc) {
    const base = Date.parse(fc.t0);
    const start = `${X(base)},${Y(hist[hist.length - 1].mgdl)}`;
    const fx = fc.horizons_min.map((h) => X(base + h * 60e3));
    const up = fx.map((x, i) => `${x},${Y(fc.hi[i])}`);
    const dn = fx.map((x, i) => `${x},${Y(fc.lo[i])}`).reverse();
    band = [start, ...up, ...dn].join(" ");
    fcLine = [start, ...fx.map((x, i) => `${x},${Y(fc.mean[i])}`)].join(" ");
  }
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <line className="low" x1="0" x2={W} y1={Y(LOW_LINE)} y2={Y(LOW_LINE)} />
      <polyline className="line" points={line} />
      {fc && <polygon className="band" points={band} />}
      {fc && <polyline className="fc" points={fcLine} />}
    </svg>
  );
}
