import { useState, useEffect, useRef } from "react";
import type { CyNode, NodeData } from "./types";
import type { SearchParams } from "./api";
import "./SearchPanel.css";

type FilterType = "region" | "level" | "control_organ" | "text";

interface FilterRow {
  type: FilterType;
  value: string;
  cascade: boolean;
}

interface Props {
  selected: NodeData | null;
  onSelect: (node: CyNode) => void;
  onExpand: () => void;
  search: (params: SearchParams) => Promise<CyNode[]>;
  fetchFilterOptions: (field: string, cascade: Omit<SearchParams, "q">) => Promise<string[]>;
  allRegions: string[];
  allLevels: string[];
}

const FILTER_LABELS: Record<FilterType, string> = {
  region:        "Регион",
  level:         "Уровень",
  control_organ: "Орган",
  text:          "Текст",
};

const SKIP_PROPS = new Set(["uri"]);

const INITIAL_ROWS: FilterRow[] = [
  { type: "region", value: "", cascade: false },
  { type: "level",  value: "", cascade: false },
  { type: "text",   value: "", cascade: false },
];

export default function SearchPanel({
  selected, onSelect, onExpand,
  search, fetchFilterOptions,
  allRegions, allLevels,
}: Props) {
  const [rows, setRows] = useState<FilterRow[]>(INITIAL_ROWS);
  // dropdown options per row — null means "not loaded yet"
  const [opts, setOpts]   = useState<(string[] | null)[]>([null, null, null]);
  const [open, setOpen]   = useState<number | null>(null);
  const [results, setResults] = useState<CyNode[]>([]);
  const [busy, setBusy]   = useState(false);

  // debounced search
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    const hasAny = rows.some(r => r.value.trim());
    if (!hasAny) { setResults([]); return; }
    searchTimer.current = setTimeout(async () => {
      setBusy(true);
      try {
        const params: SearchParams = {};
        for (const r of rows) {
          if (!r.value.trim()) continue;
          if      (r.type === "region")        params.region        = r.value;
          else if (r.type === "level")         params.level         = r.value;
          else if (r.type === "control_organ") params.control_organ = r.value;
          else if (r.type === "text")          params.q             = r.value;
        }
        setResults(await search(params));
      } finally {
        setBusy(false);
      }
    }, 350);
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
  }, [rows, search]);

  // Build cascade context (active values of rows 0..idx-1)
  const cascadeCtx = (idx: number): Omit<SearchParams, "q"> => {
    const ctx: Omit<SearchParams, "q"> = {};
    for (let i = 0; i < idx; i++) {
      const r = rows[i];
      if (!r.value.trim()) continue;
      if      (r.type === "region")        ctx.region        = r.value;
      else if (r.type === "level")         ctx.level         = r.value;
      else if (r.type === "control_organ") ctx.control_organ = r.value;
    }
    return ctx;
  };

  // Базовый список для типа без каскада
  const baseOptions = (type: FilterType): string[] => {
    if (type === "region") return allRegions;
    if (type === "level")  return allLevels;
    return [];
  };

  const loadOpts = async (idx: number, inputVal: string) => {
    const row = rows[idx];
    if (row.type === "text") { setOpts(p => { const n=[...p]; n[idx]=null; return n; }); return; }

    let base: string[];
    if (row.cascade && idx > 0) {
      base = await fetchFilterOptions(row.type, cascadeCtx(idx));
    } else if (row.type === "control_organ") {
      base = await fetchFilterOptions("control_organ", {});
    } else {
      base = baseOptions(row.type);
    }

    const q = inputVal.trim().toLowerCase();
    const filtered = q ? base.filter(o => o.toLowerCase().includes(q)) : base;
    setOpts(p => { const n=[...p]; n[idx]=filtered.slice(0, 40); return n; });
  };

  const setType = (idx: number, type: FilterType) => {
    setRows(p => p.map((r, i) => i === idx ? { ...r, type, value: "" } : r));
    setOpts(p => { const n=[...p]; n[idx]=null; return n; });
  };

  const setValue = (idx: number, value: string) => {
    setRows(p => p.map((r, i) => i === idx ? { ...r, value } : r));
    loadOpts(idx, value);
    setOpen(idx);
  };

  const selectOpt = (idx: number, val: string) => {
    setRows(p => p.map((r, i) => i === idx ? { ...r, value: val } : r));
    setOpen(null);
  };

  const clearRow = (idx: number) => {
    setRows(p => p.map((r, i) => i === idx ? { ...r, value: "" } : r));
    setOpts(p => { const n=[...p]; n[idx]=null; return n; });
  };

  const toggleCascade = (idx: number) => {
    setRows(p => p.map((r, i) => i === idx ? { ...r, cascade: !r.cascade } : r));
    setOpts(p => { const n=[...p]; n[idx]=null; return n; }); // force reload on next focus
  };

  const onFocus = (idx: number) => {
    loadOpts(idx, rows[idx].value);
    setOpen(idx);
  };

  const propEntries = selected
    ? Object.entries(selected.props).filter(
        ([k, v]) => !SKIP_PROPS.has(k) && v !== null && v !== undefined && v !== ""
      )
    : [];

  return (
    <aside className="sidebar">
      <div className="sidebar-section filter-section">
        {rows.map((row, idx) => (
          <div key={idx} className="filter-row">
            <select
              className="filter-type-sel"
              value={row.type}
              onChange={e => setType(idx, e.target.value as FilterType)}
            >
              <option value="region">Регион</option>
              <option value="level">Уровень</option>
              <option value="control_organ">Орган</option>
              <option value="text">Текст</option>
            </select>

            <div className="filter-combo">
              <input
                className="filter-input"
                type="text"
                placeholder={FILTER_LABELS[row.type] + "…"}
                value={row.value}
                onChange={e => setValue(idx, e.target.value)}
                onFocus={() => onFocus(idx)}
                onKeyDown={e => e.key === "Escape" && setOpen(null)}
                onBlur={() => setTimeout(() => setOpen(null), 160)}
              />
              {row.value && (
                <button className="filter-clr" onClick={() => clearRow(idx)}>×</button>
              )}
              {open === idx && opts[idx] && opts[idx]!.length > 0 && (
                <ul className="filter-drop">
                  {opts[idx]!.map(o => (
                    <li
                      key={o}
                      className="filter-drop-item"
                      onMouseDown={() => selectOpt(idx, o)}
                    >
                      {o}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {idx > 0 && (
              <button
                className={`cascade-btn${row.cascade ? " on" : ""}`}
                title={row.cascade ? "Каскад включён — опции зависят от строк выше" : "Каскад выключен — независимый фильтр"}
                onClick={() => toggleCascade(idx)}
              >
                ⛓
              </button>
            )}
          </div>
        ))}

        {busy && <div className="search-hint">поиск…</div>}
        {!busy && results.length === 0 && rows.some(r => r.value.trim()) && (
          <div className="search-hint">ничего не найдено</div>
        )}

        <ul className="results-list">
          {results.map(n => {
            const p = n.data.props as Record<string, unknown>;
            const sub = (p.g_region as string | undefined) ?? "";
            const levels = Array.isArray(p.g_edu_levels)
              ? (p.g_edu_levels as string[]).slice(0, 3).join(", ")
              : "";
            return (
              <li key={n.data.id} className="result-item" onClick={() => onSelect(n)}>
                <span className={`tag tag-${n.data.table}`}>{n.data.tableLabel}</span>
                <span className="result-label">{n.data.label}</span>
                {sub  && <span className="result-sub">{sub}</span>}
                {levels && <span className="result-sub result-levels">{levels}</span>}
              </li>
            );
          })}
        </ul>
      </div>

      {selected && (
        <div className="sidebar-section node-info">
          <div className="node-info-header">
            <span className={`tag tag-${selected.table}`}>{selected.tableLabel}</span>
            <button className="btn btn-primary" onClick={onExpand}>Раскрыть соседей</button>
          </div>
          <div className="node-info-label">{selected.label}</div>
          <dl className="props-list">
            {propEntries.map(([k, v]) => (
              <div key={k} className="prop-row">
                <dt>{k}</dt>
                <dd>{Array.isArray(v) ? (v as unknown[]).join(", ") : String(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </aside>
  );
}
