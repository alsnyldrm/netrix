export type TopologyDevice = {
  id: string;
  name: string;
  management_ip: string;
  kind?: string;
  archived?: boolean;
};
export type TopologyLink = {
  id: string;
  device_id: string;
  remote_device_id?: string | null;
  source: string;
  confidence: number;
  interface_name?: string;
  remote_port?: string;
  local_aggregate?: { name: string; type: string } | null;
};

function tier(device: TopologyDevice) {
  if (device.kind === "firewall") return 0;
  if (
    ["backbone", "controller", "wireless_controller"].includes(
      device.kind || "",
    ) ||
    /(?:^|-)BB(?:-|$)/i.test(device.name)
  )
    return 1;
  return 2;
}

export function layoutTopology(
  devices: TopologyDevice[],
  links: TopologyLink[],
) {
  const nodes = devices
    .filter((d) => !d.archived)
    .sort((a, b) => tier(a) - tier(b) || a.name.localeCompare(b.name));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const adjacent = new Map(nodes.map((n) => [n.id, new Set<string>()]));
  const pairs = new Map<string, TopologyLink>();
  for (const link of links) {
    const remote = link.remote_device_id;
    if (
      !remote ||
      remote === link.device_id ||
      !byId.has(remote) ||
      !byId.has(link.device_id)
    )
      continue;
    adjacent.get(link.device_id)!.add(remote);
    adjacent.get(remote)!.add(link.device_id);
    const key = [link.device_id, remote].sort().join(":");
    if (!pairs.has(key) || pairs.get(key)!.confidence < link.confidence)
      pairs.set(key, link);
  }
  const levels = new Map<string, number>();
  const queue: string[] = [];
  for (const node of nodes) {
    // Seed infrastructure tiers before traversing links so a controller reached
    // through a backbone stays beside it rather than falling into the edge tier.
    if (tier(node) <= 1) {
      levels.set(node.id, tier(node));
      queue.push(node.id);
    }
  }
  function visit() {
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      for (const peer of adjacent.get(id)!) {
        if (!levels.has(peer)) {
          levels.set(peer, levels.get(id)! + 1);
          queue.push(peer);
        }
      }
    }
  }
  visit();
  // Each disconnected component gets its own root, with cycles bounded by visited nodes.
  for (const node of nodes) {
    if (!levels.has(node.id)) {
      levels.set(node.id, 2);
      queue.length = 0;
      queue.push(node.id);
      visit();
    }
  }
  const rows = new Map<number, TopologyDevice[]>();
  for (const node of nodes) {
    const level = levels.get(node.id)!;
    rows.set(level, [...(rows.get(level) || []), node]);
  }
  // Size columns from actual labels, so names and IPv6 addresses are never truncated.
  const cell = Math.max(
    280,
    ...nodes.map(
      (n) => Math.max(n.name.length * 8, n.management_ip.length * 8) + 48,
    ),
  );
  const width = Math.max(
    800,
    ...[...rows.values()].map((row) => row.length * cell + 64),
  );
  const height = Math.max(240, (Math.max(0, ...rows.keys()) + 1) * 140 + 40);
  const positions = new Map<string, { x: number; y: number }>();
  for (const [level, row] of rows) {
    row.forEach((node, index) =>
      positions.set(node.id, {
        x: (width - (row.length - 1) * cell) / 2 + index * cell,
        y: 66 + level * 140,
      }),
    );
  }
  return {
    nodes,
    links: [...pairs.values()],
    positions,
    width,
    height,
    cardWidth: cell - 32,
  };
}
