// The effective inventory vendor can come from discovery or a manual edit.
const vendors = [
  ["alcatelenterprise.png", "Alcatel-Lucent Enterprise", "ALE"],
  ["arista", "Arista", "Arista Networks", "Arista EOS"],
  [
    "aruba",
    "Aruba",
    "Aruba Networks",
    "HPE Aruba",
    "HPE Aruba Networking",
    "HPE Aruba Networks",
    "Aruba a Hewlett Packard Enterprise company",
  ],
  ["asus", "ASUS", "ASUSTeK", "ASUSTeK Computer"],
  ["cambium", "Cambium Networks", "Cambium"],
  [
    "checkpoint",
    "Check Point",
    "Check Point Software",
    "Check Point Software Technologies",
  ],
  ["cisco", "Cisco", "Cisco Systems"],
  [
    "dell",
    "Dell",
    "Dell Technologies",
    "Dell EMC",
    "Dell Networking",
    "Force10",
    "Dell Force10",
  ],
  ["dlink", "D-Link"],
  ["ericsson", "Ericsson"],
  ["extreme", "Extreme Networks", "Extreme", "Enterasys", "Enterasys Networks"],
  ["f5", "F5", "F5 Networks", "F5 BIG-IP"],
  ["fortinet", "Fortinet", "FortiGate"],
  ["fujitsu", "Fujitsu"],
  ["h3c.png", "H3C", "H3C Technologies", "New H3C Technologies"],
  ["hp", "HP", "Hewlett-Packard", "HP ProCurve", "HP Networking", "ProCurve"],
  [
    "hpe",
    "HPE",
    "Hewlett Packard Enterprise",
    "HPE Networking",
    "HP Enterprise",
  ],
  ["huawei", "Huawei", "Huawei Technologies"],
  [
    "junipernetworks",
    "Juniper",
    "Juniper Networks",
    "HPE Juniper Networking",
    "HPE Juniper",
    "HPE Juniper Networks",
    "Juniper Mist",
  ],
  ["lenovo", "Lenovo", "Lenovo Group"],
  ["linksys", "Linksys", "Cisco Linksys"],
  ["meraki", "Cisco Meraki", "Meraki"],
  ["mikrotik", "MikroTik", "Mikrotikls", "RouterBOARD", "MikroTik RouterOS"],
  ["netapp", "NetApp"],
  ["netgear", "NETGEAR"],
  [
    "nokia",
    "Nokia",
    "Nokia Networks",
    "Nokia Solutions and Networks",
    "Alcatel-Lucent",
  ],
  ["openwrt", "OpenWrt"],
  ["opnsense", "OPNsense", "Deciso"],
  ["paloaltonetworks", "Palo Alto Networks", "Palo Alto", "PAN-OS"],
  ["pfsense", "pfSense", "Netgate"],
  ["qnap", "QNAP", "QNAP Systems"],
  ["sonicwall", "SonicWall", "Dell SonicWall"],
  ["sophos", "Sophos"],
  ["synology", "Synology"],
  ["tplink", "TP-Link", "TP-Link Technologies", "TP-Link Omada", "Omada"],
  ["ubiquiti", "Ubiquiti", "Ubiquiti Networks", "Ubiquiti UniFi", "UniFi"],
  ["vmware", "VMware", "VMware by Broadcom"],
  ["watchguard", "WatchGuard", "WatchGuard Technologies"],
  ["zte", "ZTE", "ZTE Corporation"],
  ["zyxel", "Zyxel", "Zyxel Networks", "Zyxel Communications"],
] as const;

function vendorKey(name: string) {
  return name
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .trim()
    .replace(/[.,]+$/g, "")
    .replace(
      /(?:[\s,.]+(?:incorporated|inc|corporation|corp|company|limited|ltd|llc|gmbh|co))+(?:[.,\s]+)?$/g,
      "",
    )
    .replace(/[^a-z0-9]/g, "");
}

const logoByVendor = new Map(
  vendors.flatMap(([asset, ...names]) =>
    names.map(
      (name) =>
        [
          vendorKey(name),
          `/vendor-logos/${asset.includes(".") ? asset : asset + ".svg"}`,
        ] as const,
    ),
  ),
);

export const deviceVendorNames = vendors.map(([, name]) => name);

export function deviceVendorLogo(vendor: string | null | undefined) {
  return vendor ? logoByVendor.get(vendorKey(vendor)) : undefined;
}
