import { useState, useCallback } from "react";
import type { CyNode, CyEdge, GraphPatch, NodeData } from "./types";
import { search, expand } from "./api";
import SearchPanel from "./SearchPanel";
import GraphCanvas from "./GraphCanvas";
import "./App.css";

export default function App() {
  const [nodes, setNodes] = useState<CyNode[]>([]);
  const [edges, setEdges] = useState<CyEdge[]>([]);
  const [selected, setSelected] = useState<NodeData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyPatch = useCallback((patch: GraphPatch, focusId?: string) => {
    setNodes((prev) => {
      const map = new Map(prev.map((n) => [n.data.id, n]));
      patch.nodes.forEach((n) => map.set(n.data.id, n));
      return [...map.values()];
    });
    setEdges((prev) => {
      const map = new Map(prev.map((e) => [e.data.id, e]));
      patch.edges.forEach((e) => map.set(e.data.id, e));
      return [...map.values()];
    });
    if (focusId) {
      const node = patch.nodes.find((n) => n.data.id === focusId);
      if (node) setSelected(node.data);
    }
  }, []);

  const handleSearchSelect = useCallback(async (node: CyNode) => {
    setLoading(true);
    setError(null);
    try {
      const patch = await expand(node.data.id);
      applyPatch(patch, node.data.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [applyPatch]);

  const handleExpandSelected = useCallback(async () => {
    if (!selected) return;
    setLoading(true);
    setError(null);
    try {
      const patch = await expand(selected.id);
      applyPatch(patch);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [selected, applyPatch]);

  const handleClear = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setSelected(null);
    setError(null);
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">Реестр аккредитации — граф</span>
        {loading && <span className="app-loading">загрузка…</span>}
        {error && <span className="app-error">{error}</span>}
        <button className="btn btn-ghost" onClick={handleClear}>Очистить граф</button>
      </header>
      <div className="app-body">
        <SearchPanel
          selected={selected}
          onSelect={handleSearchSelect}
          onExpand={handleExpandSelected}
          search={search}
        />
        <GraphCanvas
          nodes={nodes}
          edges={edges}
          selectedId={selected?.id ?? null}
          onSelect={setSelected}
        />
      </div>
    </div>
  );
}
