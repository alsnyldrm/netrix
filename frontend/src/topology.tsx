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
  const pairKey = (link: TopologyLink) =>
    [link.device_id, link.remote_device_id].sort().join(":");
  const name = (id: string) =>
    devices.find((device) => device.id === id)?.name || "Cihaz bilinmiyor";
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 420 });
  const [zoom, setZoom] = useState(1);
  const [fitToViewport, setFitToViewport] = useState(false);
  useLayoutEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      // clientWidth/clientHeight round fractional CSS pixels at browser zoom.
      // Rounding up can toggle both scrollbars and trigger a resize loop.
      const { width, height } = entry.contentRect;
      setSize((current) =>
        current.width === width && current.height === height
          ? current
          : { width, height },
      );
    });
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
                >
                  <title>
                    {links
                      .filter(
                        (candidate) => pairKey(candidate) === pairKey(link),
                      )
                      .map(
                        (candidate) =>
                          `${name(candidate.device_id)} ${candidate.interface_name || "?"} → ${name(candidate.remote_device_id!)} ${candidate.remote_port || "?"}${candidate.local_aggregate ? ` · ${candidate.local_aggregate.name}` : ""}`,
                      )
                      .join("; ")}
                  </title>
                </path>
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

export function TopologyConnections({
  devices,
  links,
}: {
  devices: TopologyDevice[];
  links: TopologyLink[];
}) {
  const graph = useMemo(() => layoutTopology(devices, links), [devices, links]);
  const [selectedPair, setSelectedPair] = useState("");
  const [connectionSearch, setConnectionSearch] = useState("");
  const pairKey = (link: TopologyLink) =>
    [link.device_id, link.remote_device_id].sort().join(":");
  const normalize = (value: string) =>
    value.toLocaleLowerCase("tr-TR").replaceAll("ı", "i");
  const connectionIndex = useMemo(() => {
    const deviceById = new Map(devices.map((device) => [device.id, device]));
    const entries = new Map<string, string[]>();
    for (const link of links) {
      const key = pairKey(link);
      const values = entries.get(key) || [];
      for (const id of [link.device_id, link.remote_device_id]) {
        const device = id ? deviceById.get(id) : undefined;
        if (device) values.push(device.name, device.management_ip);
      }
      values.push(
        link.interface_name || "",
        link.remote_port || "",
        link.local_aggregate?.name || "",
      );
      entries.set(key, values);
    }
    return new Map(
      [...entries].map(([key, values]) => [key, normalize(values.join(" "))]),
    );
  }, [devices, links]);
  const searchTerms = normalize(connectionSearch.trim())
    .split(/\s+/)
    .filter(Boolean);
  const visibleConnections = graph.links.filter((link) =>
    searchTerms.every((term) =>
      connectionIndex.get(pairKey(link))?.includes(term),
    ),
  );
  const selected = visibleConnections.find(
    (link) => pairKey(link) === selectedPair,
  );
  const pairLinks = selected
    ? links.filter((link) => pairKey(link) === selectedPair)
    : [];
  const portRows = new Map<
    string,
    {
      local: string;
      remote: string;
      localGroup: string;
      remoteGroup: string;
      sources: Set<string>;
    }
  >();
  for (const link of pairLinks) {
    const forward = link.device_id === selected!.device_id;
    const local =
      (forward ? link.interface_name : link.remote_port) || "Port bilinmiyor";
    const remote =
      (forward ? link.remote_port : link.interface_name) || "Port bilinmiyor";
    const key = `${local}:${remote}`;
    const row = portRows.get(key) || {
      local,
      remote,
      localGroup: "",
      remoteGroup: "",
      sources: new Set<string>(),
    };
    if (link.local_aggregate)
      row[forward ? "localGroup" : "remoteGroup"] =
        `${link.local_aggregate.name} · ${link.local_aggregate.type}`;
    link.source.split("+").forEach((source) => row.sources.add(source));
    portRows.set(key, row);
  }
  const name = (id: string) =>
    devices.find((device) => device.id === id)?.name || "Cihaz bilinmiyor";
  return (
    <>
      {graph.links.length ? (
        <section className="panel topology-link-detail">
          <div className="topology-link-filters">
            <label>
              Bağlantılarda ara
              <input
                type="search"
                placeholder="Cihaz adı, IP veya port…"
                value={connectionSearch}
                onChange={(event) => {
                  setConnectionSearch(event.target.value);
                  setSelectedPair("");
                }}
              />
            </label>
            <label>
              Bağlantı ayrıntısı
              <select
                aria-label="Bağlantı ayrıntısı"
                name="topology-connection"
                disabled={!visibleConnections.length}
                value={selected ? selectedPair : ""}
                onChange={(event) => setSelectedPair(event.target.value)}
              >
                <option value="">
                  {visibleConnections.length
                    ? "Portlarını görmek için bağlantı seçin"
                    : "Aramanıza uygun bağlantı yok"}
                </option>
                {visibleConnections.map((link) => (
                  <option key={link.id} value={pairKey(link)}>
                    {name(link.device_id)} ↔ {name(link.remote_device_id!)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {connectionSearch.trim() && (
            <small role="status">
              {visibleConnections.length} bağlantı bulundu.
            </small>
          )}
          {selected ? (
            <div aria-live="polite">
              <div className="topology-port-heading">
                <strong>{name(selected.device_id)}</strong>
                <strong>{name(selected.remote_device_id!)}</strong>
              </div>
              <ul>
                {[...portRows.entries()].map(([key, row]) => (
                  <li key={key}>
                    <span className="mono">
                      {row.local}
                      {row.localGroup ? (
                        <small className="topology-port-group">
                          {row.localGroup}
                        </small>
                      ) : null}
                    </span>
                    <span className="mono">
                      {row.remote}
                      {row.remoteGroup ? (
                        <small className="topology-port-group">
                          {row.remoteGroup}
                        </small>
                      ) : null}
                    </span>
                    <small>
                      {[...row.sources].map((s) => s.toUpperCase()).join(" + ")}
                    </small>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
