export interface NodeData {
  id: string;
  label: string;
  table: string;
  tableLabel: string;
  props: Record<string, unknown>;
}

export interface CyNode {
  data: NodeData;
}

export interface CyEdge {
  data: {
    id: string;
    source: string;
    target: string;
    label: string;
  };
}

export interface GraphPatch {
  nodes: CyNode[];
  edges: CyEdge[];
}
