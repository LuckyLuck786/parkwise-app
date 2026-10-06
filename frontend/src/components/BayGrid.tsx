import { useMemo } from "react";
import { Bay } from "../types";

const CELL_W = 74;
const CELL_H = 52;
const GAP = 8;
const PAD = 18;

interface Props {
  bays: Bay[];
  title?: string;
  selectedId?: string | null;
  onSelect?: (bay: Bay) => void;
  compact?: boolean;
}

const STATE_STYLE: Record<string, { fill: string; stroke: string; dash: string }> = {
  free: { fill: "#dcfce7", stroke: "#16a34a", dash: "4 3" },
  allotted: { fill: "#fef3c7", stroke: "#d97706", dash: "" },
  occupied: { fill: "#e2e8f0", stroke: "#475569", dash: "" },
  blocked: { fill: "#fee2e2", stroke: "#e11d48", dash: "" },
  unknown: { fill: "#f5f3ff", stroke: "#7c3aed", dash: "2 3" },
};

const STATE_GLYPH: Record<string, string> = {
  free: "○",
  allotted: "⏳",
  occupied: "P",
  blocked: "✕",
  unknown: "?",
};

const STATE_WORD: Record<string, string> = {
  free: "free",
  allotted: "allotted (held, not yet arrived)",
  occupied: "occupied",
  blocked: "blocked",
  unknown: "unknown",
};

function describeBay(bay: Bay): string {
  const parts = [
    `Bay ${bay.label}`,
    STATE_WORD[bay.state] ?? bay.state,
    bay.type === "two_wheeler" ? "two-wheeler" : "four-wheeler",
  ];
  if (bay.is_accessible) parts.push("accessible bay");
  if (bay.reserved_tier) parts.push(`reserved for tier ${bay.reserved_tier} until cut-off`);
  if (bay.low_confidence) parts.push("low confidence sensor reading");
  if (bay.nearest_building) parts.push(`nearest building ${bay.nearest_building}`);
  if (bay.allotment?.plate) parts.push(`assigned vehicle ${bay.allotment.plate}`);
  return parts.join(", ");
}

/**
 * Live lot map: one rectangle per bay, laid out from the stored x/y grid.
 *
 * Accessibility: state is never encoded by colour alone — every bay carries a
 * glyph and a full text label, the group is keyboard focusable, and each shape
 * exposes an aria-label describing state, type, reservation and confidence.
 */
export default function BayGrid({ bays, title, selectedId, onSelect, compact }: Props) {
  const geom = useMemo(() => {
    if (bays.length === 0) return { cols: 0, rows: 0, width: 0, height: 0 };
    const cols = Math.max(...bays.map((b) => b.x)) + 1;
    const rows = Math.max(...bays.map((b) => b.y)) + 1;
    return {
      cols,
      rows,
      width: cols * (CELL_W + GAP) + PAD * 2,
      height: rows * (CELL_H + GAP) + PAD * 2 + 16,
    };
  }, [bays]);

  if (bays.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        No bays to show yet — add bays in the Bay Editor.
      </p>
    );
  }

  const font = compact ? 9 : 11;

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${geom.width} ${geom.height}`}
        className="h-auto w-full min-w-[420px]"
        role="group"
        aria-label={title ? `${title} bay grid` : "Bay grid"}
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <pattern id="hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="#f5f3ff" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#7c3aed" strokeWidth="2" />
          </pattern>
          <g id="wheelchair">
            <circle cx="0" cy="0" r="6.5" fill="#ffffff" stroke="#1d4ed8" strokeWidth="1.5" />
            <text
              x="0"
              y="3.4"
              textAnchor="middle"
              fontSize="9"
              fill="#1d4ed8"
              fontWeight="700"
              aria-hidden
            >
              ♿
            </text>
          </g>
        </defs>

        {/* Lot entrance marker */}
        <g aria-hidden>
          <text x={PAD} y={14} fontSize={font} fill="#475569" fontWeight="700">
            ENTRANCE
          </text>
          <path
            d={`M ${PAD} 18 L ${PAD + 46} 18`}
            stroke="#475569"
            strokeWidth="2"
            markerEnd=""
          />
        </g>

        {bays.map((bay) => {
          const style = STATE_STYLE[bay.state] ?? STATE_STYLE.unknown;
          const x = PAD + bay.x * (CELL_W + GAP);
          const y = PAD + 8 + bay.y * (CELL_H + GAP);
          const selected = selectedId === bay.id;
          return (
            <g
              key={bay.id}
              transform={`translate(${x}, ${y})`}
              className={onSelect ? "cursor-pointer" : undefined}
              role={onSelect ? "button" : "img"}
              tabIndex={onSelect ? 0 : undefined}
              aria-label={describeBay(bay)}
              onClick={onSelect ? () => onSelect(bay) : undefined}
              onKeyDown={
                onSelect
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelect(bay);
                      }
                    }
                  : undefined
              }
            >
              <title>{describeBay(bay)}</title>
              <rect
                className="bay-shape"
                width={CELL_W}
                height={CELL_H}
                rx="6"
                fill={bay.state === "unknown" ? "url(#hatch)" : style.fill}
                stroke={selected ? "#1d4ed8" : style.stroke}
                strokeWidth={selected ? 3 : 1.6}
                strokeDasharray={style.dash}
              />
              <text
                className="bay-label"
                x={CELL_W / 2}
                y={17}
                textAnchor="middle"
                fontSize={font}
                fontWeight="700"
                fill="#0f172a"
              >
                {bay.label}
              </text>
              <text
                x={CELL_W / 2}
                y={36}
                textAnchor="middle"
                fontSize={font + 4}
                fill={bay.state === "occupied" ? "#334155" : style.stroke}
                fontWeight="700"
                aria-hidden
              >
                {STATE_GLYPH[bay.state] ?? "?"}
              </text>

              {bay.is_accessible && (
                <g transform={`translate(${CELL_W - 11}, 11)`} aria-hidden>
                  <use href="#wheelchair" />
                </g>
              )}
              {bay.reserved_tier ? (
                <g aria-hidden>
                  <rect
                    x="4"
                    y={CELL_H - 15}
                    width="24"
                    height="12"
                    rx="6"
                    fill="#1e40af"
                  />
                  <text x="16" y={CELL_H - 6} textAnchor="middle" fontSize="8" fill="#fff" fontWeight="700">
                    T{bay.reserved_tier}
                  </text>
                </g>
              ) : null}
              {bay.low_confidence && (
                <g aria-hidden>
                  <circle cx="12" cy="12" r="7" fill="#fff" stroke="#b45309" strokeWidth="1.5" />
                  <text x="12" y="15.5" textAnchor="middle" fontSize="10" fill="#b45309" fontWeight="800">
                    !
                  </text>
                </g>
              )}
              {bay.type === "two_wheeler" && (
                <text x={CELL_W - 6} y={CELL_H - 5} textAnchor="end" fontSize="8" fill="#64748b" aria-hidden>
                  2W
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function BayLegend() {
  const items: { key: string; label: string }[] = [
    { key: "free", label: "Free (○)" },
    { key: "allotted", label: "Allotted, not arrived (⏳)" },
    { key: "occupied", label: "Occupied (P)" },
    { key: "blocked", label: "Blocked (✕)" },
    { key: "unknown", label: "Unknown / no data (?)" },
  ];
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-600">
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <svg width="18" height="14" aria-hidden>
            <rect
              width="16"
              height="12"
              rx="2"
              fill={
                item.key === "unknown"
                  ? "url(#hatch)"
                  : (STATE_STYLE[item.key]?.fill ?? "#eee")
              }
              stroke={STATE_STYLE[item.key]?.stroke ?? "#999"}
              strokeDasharray={STATE_STYLE[item.key]?.dash || undefined}
            />
          </svg>
          <span>{item.label}</span>
        </li>
      ))}
      <li className="flex items-center gap-1.5">
        <span aria-hidden className="text-[13px]">♿</span> Accessible bay
      </li>
      <li className="flex items-center gap-1.5">
        <span aria-hidden className="rounded bg-brand-700 px-1 text-[9px] font-bold text-white">T2</span>
        Tier 2 reserved
      </li>
      <li className="flex items-center gap-1.5">
        <span aria-hidden className="rounded-full border border-amber-600 px-1.5 text-[10px] font-bold text-amber-700">!</span>
        Low confidence
      </li>
    </ul>
  );
}
