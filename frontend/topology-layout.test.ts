import assert from "node:assert/strict";
import { layoutTopology } from "./src/topology-layout.ts";
const devices = [
  { id: "f", name: "firewall", kind: "firewall", management_ip: "192.0.2.1" },
  { id: "b", name: "core", kind: "backbone", management_ip: "192.0.2.2" },
  {
    id: "c",
    name: "controller",
    kind: "controller",
    management_ip: "192.0.2.3",
  },
  ...Array.from({ length: 15 }, (_, i) => ({
    id: `e${i}`,
    name: `edge-${i}`,
    kind: "switch",
    management_ip: `192.0.2.${i + 4}`,
  })),
];
const links = [
  ["f", "b"],
  ["b", "c"],
  ["b", "e0"],
  ["e0", "e1"],
  ["e1", "e2"],
  ["e2", "e0"],
  ["b", "f"],
  ["b", "missing"],
].map(([from, to], i) => ({
  id: `l${i}`,
  device_id: from,
  remote_device_id: to,
  confidence: i === 6 ? 1 : 0.65,
  source: "lldp",
}));
const result = layoutTopology(devices, links);
assert.equal(result.nodes.length, 18);
assert.equal(result.links.length, 6);
assert.equal(result.links.find((l) => l.id === "l6")?.confidence, 1);
const y = (id: string) => result.positions.get(id)!.y;
assert(y("f") < y("b"));
assert.equal(y("b"), y("c"));
assert(y("b") < y("e0"));
assert(y("e0") < y("e1"));
assert.equal(layoutTopology([], []).nodes.length, 0);
assert.deepEqual(
  [...result.positions],
  [...layoutTopology([...devices].reverse(), links).positions],
);
assert.equal(
  layoutTopology([{ ...devices[0], archived: true }], links).nodes.length,
  0,
);
console.log(
  "topology layout: hierarchy, cycles, >12 devices, duplicates, unresolved endpoints, stable ordering PASS",
);
