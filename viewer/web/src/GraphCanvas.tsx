import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";
import type { CyNode, CyEdge, NodeData } from "./types";
import "./GraphCanvas.css";

const NODE_COLORS: Record<string, string> = {
  certificate:                  "#1976d2",
  supplement:                   "#388e3c",
  educational_program:          "#f57c00",
  educational_level:            "#7b1fa2",
  region:                       "#c62828",
  actual_education_organization:"#00796b",
  decision:                     "#546e7a",
};

interface Props {
  nodes: CyNode[];
  edges: CyEdge[];
  selectedId: string | null;
  onSelect: (node: NodeData | null) => void;
}

export default function GraphCanvas({ nodes, edges, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);

  // init cytoscape once
  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      style: [
        {
          selector: "node",
          style: {
            "background-color": (ele) => NODE_COLORS[ele.data("table")] ?? "#888",
            "label": "data(label)",
            "color": "#fff",
            "font-size": 10,
            "text-valign": "center",
            "text-halign": "center",
            "text-wrap": "wrap",
            "text-max-width": "90px",
            "width": 60,
            "height": 60,
            "border-width": 0,
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-width": 3,
            "border-color": "#fff",
          },
        },
        {
          selector: "edge",
          style: {
            "width": 1.5,
            "line-color": "#bbb",
            "target-arrow-color": "#bbb",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "label": "data(label)",
            "font-size": 9,
            "color": "#666",
            "text-rotation": "autorotate",
          },
        },
      ],
      layout: { name: "cose" },
      wheelSensitivity: 0.3,
    });

    cy.on("tap", "node", (evt) => {
      onSelect(evt.target.data() as NodeData);
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) onSelect(null);
    });

    cyRef.current = cy;
    return () => { cy.destroy(); cyRef.current = null; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // sync elements
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const existingNodeIds = new Set(cy.nodes().map((n) => n.id()));
    const existingEdgeIds = new Set(cy.edges().map((e) => e.id()));

    const newNodes = nodes.filter((n) => !existingNodeIds.has(n.data.id));
    const newEdges = edges.filter((e) => !existingEdgeIds.has(e.data.id));

    if (newNodes.length === 0 && newEdges.length === 0) return;

    cy.add([...newNodes, ...newEdges]);

    // re-layout only new nodes; animate
    cy.layout({
      name: "cose",
      animate: true,
      animationDuration: 400,
      fit: false,
      randomize: false,
    } as cytoscape.LayoutOptions).run();
  }, [nodes, edges]);

  // highlight selected node
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().unselect();
    if (selectedId) {
      const node = cy.getElementById(selectedId);
      if (node.length) {
        node.select();
        cy.animate({ center: { eles: node }, zoom: cy.zoom() < 0.8 ? 1 : undefined } as Parameters<typeof cy.animate>[0]);
      }
    }
  }, [selectedId]);

  // clear
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    if (nodes.length === 0 && edges.length === 0) cy.elements().remove();
  }, [nodes, edges]);

  return <div ref={containerRef} className="graph-canvas" />;
}
