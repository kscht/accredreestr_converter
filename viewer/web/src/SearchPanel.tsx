import { useState, useEffect, useRef } from "react";
import type { CyNode, NodeData } from "./types";
import "./SearchPanel.css";

interface Props {
  selected: NodeData | null;
  onSelect: (node: CyNode) => void;
  onExpand: () => void;
  search: (q: string) => Promise<CyNode[]>;
}

const SKIP_PROPS = new Set(["uri"]);

export default function SearchPanel({ selected, onSelect, onExpand, search }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CyNode[]>([]);
  const [searching, setSearching] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!query.trim()) { setResults([]); return; }
    timer.current = setTimeout(async () => {
      setSearching(true);
      try {
        setResults(await search(query));
      } finally {
        setSearching(false);
      }
    }, 350);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [query, search]);

  const propEntries = selected
    ? Object.entries(selected.props).filter(
        ([k, v]) => !SKIP_PROPS.has(k) && v !== null && v !== undefined && v !== ""
      )
    : [];

  return (
    <aside className="sidebar">
      <div className="sidebar-section">
        <input
          className="search-input"
          type="text"
          placeholder="Название, ОГРН или ИНН…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {searching && <div className="search-hint">поиск…</div>}
        {!searching && results.length === 0 && query.trim() && (
          <div className="search-hint">ничего не найдено</div>
        )}
        <ul className="results-list">
          {results.map((n) => (
            <li key={n.data.id} className="result-item" onClick={() => onSelect(n)}>
              <span className={`tag tag-${n.data.table}`}>{n.data.tableLabel}</span>
              <span className="result-label">{n.data.label}</span>
              <span className="result-sub">{(n.data.props as Record<string, unknown>).RegionName as string ?? ""}</span>
            </li>
          ))}
        </ul>
      </div>

      {selected && (
        <div className="sidebar-section node-info">
          <div className="node-info-header">
            <span className={`tag tag-${selected.table}`}>{selected.tableLabel}</span>
            <button className="btn btn-primary" onClick={onExpand}>
              Раскрыть соседей
            </button>
          </div>
          <div className="node-info-label">{selected.label}</div>
          <dl className="props-list">
            {propEntries.map(([k, v]) => (
              <div key={k} className="prop-row">
                <dt>{k}</dt>
                <dd>{String(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </aside>
  );
}
