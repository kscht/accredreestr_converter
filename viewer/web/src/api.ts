import type { CyNode, GraphPatch } from "./types";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export async function search(q: string): Promise<CyNode[]> {
  const data = await get<{ nodes: CyNode[] }>(`/api/search?q=${encodeURIComponent(q)}`);
  return data.nodes;
}

export async function expand(id: string): Promise<GraphPatch> {
  return get<GraphPatch>(`/api/expand?id=${encodeURIComponent(id)}`);
}

export async function fetchRegions(): Promise<string[]> {
  const data = await get<{ regions: string[] }>("/api/regions");
  return data.regions;
}

export async function fetchLevels(): Promise<string[]> {
  const data = await get<{ levels: string[] }>("/api/levels");
  return data.levels;
}
