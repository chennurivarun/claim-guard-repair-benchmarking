import { useEffect, useRef, useState } from "react"
import cytoscape, { type Core, type StylesheetJson } from "cytoscape"
import { MaximizeIcon, MinusIcon, PlusIcon, RotateCcwIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { graphColors, type ChallengeNetwork } from "./knowledge-graph-model"

const graphStyle: StylesheetJson = [
  {
    selector: "node",
    style: {
      shape: "ellipse",
      width: 96,
      height: 96,
      "background-color": "data(color)",
      "border-width": 2,
      "border-color": "#cbd5e1",
      label: "data(caption)",
      color: "#102033",
      "font-size": 13,
      "font-weight": 600,
      "font-family": "Geist Variable, sans-serif",
      "text-valign": "center",
      "text-halign": "center",
      "text-wrap": "wrap",
      "text-max-width": "84px",
      "text-overflow-wrap": "whitespace",
    },
  },
  {
    selector: 'node[kind = "repairer"]',
    style: { color: "#ffffff", "border-color": "#93c5fd" },
  },
  {
    selector: "edge",
    style: {
      width: 1.5,
      "curve-style": "bezier",
      "line-color": "#64748b",
      "target-arrow-color": "#94a3b8",
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.8,
      label: "data(label)",
      "font-size": 10,
      color: "#cbd5e1",
      "text-rotation": "autorotate",
      "text-background-color": "#101820",
      "text-background-opacity": 1,
      "text-background-padding": "3px",
    },
  },
  { selector: ".dimmed", style: { opacity: 0.18 } },
  {
    selector: "node.highlighted",
    style: { "border-width": 4, "border-color": "#ffffff" },
  },
  {
    selector: "edge.highlighted",
    style: {
      width: 3,
      "line-color": "#e2e8f0",
      "target-arrow-color": "#e2e8f0",
      "z-index": 10,
    },
  },
]

function runLayout(cy: Core) {
  cy.layout({
    name: "concentric",
    animate: false,
    padding: 32,
    minNodeSpacing: 24,
    avoidOverlap: true,
    concentric: (node) => node.degree(),
    levelWidth: () => 3,
  }).run()
}

function nodeCaption(label: string) {
  const caption = label.length > 64 ? `${label.slice(0, 61)}…` : label
  return caption
    .split(/\s+/)
    .map((word) =>
      word.length > 14 ? word.match(/.{1,12}/g)?.join("\n") : word
    )
    .join(" ")
}

export default function KnowledgeGraphCanvas({
  graph,
  selectedId,
  onSelect,
}: {
  graph: ChallengeNetwork
  selectedId: string | null
  onSelect: (id: string | null) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const instance = useRef<Core | null>(null)
  const [zoomPercent, setZoomPercent] = useState(100)

  useEffect(() => {
    if (!container.current) return
    const cy = cytoscape({
      container: container.current,
      elements: [
        ...graph.nodes.map((node) => ({
          data: {
            id: node.id,
            kind: node.kind,
            color: graphColors[node.kind],
            caption: nodeCaption(node.label),
          },
        })),
        ...graph.edges.map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.label,
          },
        })),
      ],
      style: graphStyle,
      layout: { name: "circle", padding: 42 },
      minZoom: 0.15,
      maxZoom: 3,
      selectionType: "single",
      boxSelectionEnabled: false,
    })
    instance.current = cy
    runLayout(cy)
    cy.on("tap", "node, edge", (event) => onSelect(event.target.id()))
    cy.on("tap", (event) => {
      if (event.target === cy) onSelect(null)
    })
    const reportZoom = () => setZoomPercent(Math.round(cy.zoom() * 100))
    cy.on("zoom", reportZoom)
    reportZoom()
    const observer = new ResizeObserver(() => {
      cy.resize()
      cy.fit(undefined, 42)
    })
    observer.observe(container.current)
    return () => {
      observer.disconnect()
      cy.destroy()
      instance.current = null
    }
  }, [graph, onSelect])

  useEffect(() => {
    const cy = instance.current
    if (!cy) return
    cy.batch(() => {
      cy.elements().removeClass("dimmed highlighted")
      if (!selectedId) return
      const selected = cy.getElementById(selectedId)
      if (selected.empty()) return
      const connected =
        selected.group() === "nodes"
          ? selected.closedNeighborhood()
          : selected.union(selected.connectedNodes())
      cy.elements().not(connected).addClass("dimmed")
      connected.addClass("highlighted")
    })
  }, [graph, selectedId])

  const zoom = (factor: number) => {
    const cy = instance.current
    if (cy)
      cy.zoom({
        level: Math.min(
          cy.maxZoom(),
          Math.max(cy.minZoom(), cy.zoom() * factor)
        ),
        renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
      })
  }

  return (
    <div className="relative min-w-0 self-start bg-[#101820] text-slate-200">
      <div
        ref={container}
        className="h-[520px] w-full sm:h-[600px]"
        role="img"
        aria-label={`Knowledge graph: ${graph.nodes.length} nodes and ${graph.edges.length} relationships. Use the Inspect a node selector or Table view for keyboard access.`}
      />
      <div className="absolute right-3 bottom-12 flex flex-col gap-1 rounded-lg border border-slate-600 bg-[#18232e] p-1">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Zoom in"
          onClick={() => zoom(1.2)}
        >
          <PlusIcon aria-hidden />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Zoom out"
          onClick={() => zoom(1 / 1.2)}
        >
          <MinusIcon aria-hidden />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Fit graph to view"
          onClick={() => instance.current?.fit(undefined, 42)}
        >
          <MaximizeIcon aria-hidden />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Reset graph layout"
          onClick={() => {
            if (instance.current) {
              instance.current.layout({ name: "circle" }).run()
              runLayout(instance.current)
            }
          }}
        >
          <RotateCcwIcon aria-hidden />
        </Button>
      </div>
      <div className="flex flex-wrap justify-between gap-2 border-t border-slate-700 px-4 py-3 text-xs text-slate-300">
        <span>Drag nodes to arrange · Drag canvas to pan · Scroll to zoom</span>
        <span aria-label="Graph zoom">{zoomPercent}%</span>
      </div>
    </div>
  )
}
