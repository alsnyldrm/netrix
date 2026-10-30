import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { Minus, Plus, CornersOut, Graph } from "@phosphor-icons/react";
import {
  layoutTopology,
  type TopologyDevice,
  type TopologyLink,
} from "./topology-layout";
import "./topology.css";

export function Topology<T extends TopologyDevice>({
  devices,
  links,
  onDevice,
  compact = false,
}: {
  devices: T[];
  links: TopologyLink[];
  onDevice: (row: T) => void;
  compact?: boolean;
}) {
  const graph = useMemo(() => layoutTopology(devices, links), [devices, links]);
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 420 });
  const [zoom, setZoom] = useState(1);
  const [fitToViewport, setFitToViewport] = useState(false);
  useLayoutEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      setSize({ width: element.clientWidth, height: element.clientHeight }),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [graph.nodes.length > 0]);
  const fit = Math.min(1, size.width / graph.width, size.height / graph.height);
  const baseScale = fitToViewport ? fit : Math.max(0.85, fit);
  const scale = baseScale * zoom;
  const inset = Math.max(0, (size.width - graph.width * scale) / 2);
  useLayoutEffect(() => {
    const element = viewport.current;
    if (element)
      element.scrollLeft = Math.max(
        0,
        (graph.width * baseScale - size.width) / 2,
      );
  }, [size.width, graph.width, baseScale]);
  function reset() {
    setFitToViewport(true);
    setZoom(1);
    viewport.current?.scrollTo({ left: 0, top: 0 });
  }
  if (!graph.nodes.length)
    return (
      <div className="topology-empty">
        <div className="network-seed">
          <Graph size={26} aria-hidden="true" />
          <span>Henüz cihaz yok</span>
        </div>
      </div>
    );
  return (
    <div className={`topology-map ${compact ? "compact" : ""}`}>
      <div
        className="topology-controls"
        role="group"
        aria-label="Harita ölçeği"
      >
        <button
          type="button"
          aria-label="Haritayı küçült"
          title="Küçült"
          disabled={zoom <= 0.25}
          onClick={() => setZoom((z) => Math.max(0.25, z / 1.25))}
        >
          <Minus size={18} aria-hidden="true" />
        </button>
        <output aria-label="Harita yakınlaştırma oranı" aria-live="polite">
          {Math.round(zoom * 100)}%
        </output>
        <button
          type="button"
          aria-label="Haritayı büyüt"
          title="Büyüt"
          disabled={zoom >= 8}
          onClick={() => setZoom((z) => Math.min(8, z * 1.25))}
        >
          <Plus size={18} aria-hidden="true" />
        </button>
        <button type="button" className="topology-fit" onClick={reset}>
          <CornersOut size={18} aria-hidden="true" />
          Sığdır
        </button>
      </div>
      <div
        className="topology-viewport"
        ref={viewport}
        tabIndex={0}
        role="region"
        aria-label="Cihaz bağlantı haritası"
      >
        <div
          className="topology-canvas"
          style={{
            width: Math.max(size.width, graph.width * scale),
            height: Math.max(size.height, graph.height * scale),
          }}
        >
          <svg
            className="topology-drawing"
            viewBox={`0 0 ${graph.width} ${graph.height}`}
            style={{
              left: inset,
              width: graph.width * scale,
              height: graph.height * scale,
            }}
            aria-hidden="true"
          >
            {graph.links.map((link) => {
              const a = graph.positions.get(link.device_id)!;
              const b = graph.positions.get(link.remote_device_id!)!;
              const sameRow = a.y === b.y;
              const bypass =
                sameRow && Math.abs(a.x - b.x) > graph.cardWidth + 33;
              const start = {
                x:
                  a.x +
                  (sameRow ? (Math.sign(b.x - a.x) * graph.cardWidth) / 2 : 0),
                y: a.y + (sameRow ? 0 : Math.sign(b.y - a.y) * 32),
              };
              const end = {
                x:
                  b.x +
                  (sameRow ? (Math.sign(a.x - b.x) * graph.cardWidth) / 2 : 0),
                y: b.y + (sameRow ? 0 : Math.sign(a.y - b.y) * 32),
              };
              const middle = (start.y + end.y) / 2;
              return (
                <path
                  key={link.id}
                  data-from={link.device_id}
                  data-to={link.remote_device_id}
                  className="topology-edge"
                  strokeDasharray={link.confidence < 0.9 ? "6 6" : undefined}
                  d={
                    bypass
                      ? `M${a.x},${a.y + 32} V${a.y + 60} H${b.x} V${b.y + 32}`
                      : sameRow
                        ? `M${start.x},${start.y} L${end.x},${end.y}`
                        : `M${start.x},${start.y} C${start.x},${middle} ${end.x},${middle} ${end.x},${end.y}`
                  }
                />
              );
            })}
          </svg>
          <div
            className="topology-nodes"
            style={{
              left: inset,
              width: graph.width,
              height: graph.height,
              transform: `scale(${scale})`,
            }}
          >
            {graph.nodes.map((node) => {
              const position = graph.positions.get(node.id)!;
              return (
                <button
                  className="topology-device"
                  key={node.id}
                  data-device={node.id}
                  style={{
                    left: position.x - graph.cardWidth / 2,
                    top: position.y - 32,
                    width: graph.cardWidth,
                  }}
                  onClick={() =>
                    onDevice(devices.find((d) => d.id === node.id)!)
                  }
                  aria-label={`${node.name} cihazını görüntüle`}
                >
                  <span translate="no">{node.name}</span>
                  <span className="mono" translate="no">
                    {node.management_ip}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
