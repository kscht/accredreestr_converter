import type { CyNode, GraphPatch } from "./types";

export interface SearchParams {
  q?: string;
  region?: string;
  level?: string;
  control_organ?: string;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export async function search(params: SearchParams): Promise<CyNode[]> {
  const p = new URLSearchParams();
  if (params.q)             p.set("q",             params.q);
  if (params.region)        p.set("region",         params.region);
  if (params.level)         p.set("level",          params.level);
  if (params.control_organ) p.set("control_organ",  params.control_organ);
  const data = await get<{ nodes: CyNode[] }>(`/api/search?${p}`);
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

export async function fetchFilterOptions(
  field: string,
  cascade: Omit<SearchParams, "q"> = {},
): Promise<string[]> {
  const p = new URLSearchParams({ field });
  if (cascade.region)        p.set("region",        cascade.region);
  if (cascade.level)         p.set("level",         cascade.level);
  if (cascade.control_organ) p.set("control_organ", cascade.control_organ);
  const data = await get<{ options: string[] }>(`/api/filter_options?${p}`);
  return data.options;
}
