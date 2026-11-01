import { useRef } from "react";
import type { Icon } from "@phosphor-icons/react";
import {
  ArrowUpRight,
  ArrowsClockwise,
  GearSix,
  GlobeHemisphereWest,
  Key,
  MagnifyingGlass,
  Stack,
  Sun,
  Buildings,
} from "@phosphor-icons/react";
import { useLiveQuery } from "./data";

type Row = Record<string, any>;
type Page = {
  key: string;
  title: string;
  desc: string;
  group: string;
  icon: Icon;
  fields?: { label: string }[];
};
const aliases: Record<string, string> = {
  settings:
    "ayarlar sistem platform sağlık worker redis veritabanı parola şifre hesap",
  credentials: "ayarlar snmp ssh api erişim profilleri kimlik bilgileri",
  vlans:
    "ayarlar vlan ipam ip bloğu subnet ping tarama keşif zamanlama dns eşik",
  integrations: "ayarlar entegrasyon vmware vcenter dhcp eşitleme",
  sites: "ayarlar kurum kurumlar lokasyon alt lokasyon kampüs bina kat",
  "backup-settings": "ayarlar konfigürasyon yedekleme zamanlama saklama",
  "backup-groups": "ayarlar konfigürasyon yedek grubu gruplar",
  "device-types": "ayarlar cihaz türleri",
  "dns-servers": "ayarlar dns sunucuları isim çözümleme hostname",
  vrfs: "ayarlar vrf yönlendirme alanı",
  users: "ayarlar kullanıcı hesap yetki ekip rol",
  rules: "ayarlar alarm kuralları eşik bildirim",
};
const normalized = (value: string) =>
  value
    .toLocaleLowerCase("tr-TR")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replaceAll("ı", "i");

export function WorkspaceSearch({
  pages,
  query,
  setQuery,
  admin,
  navigate,
  onDevice,
  onVLAN,
  onSettings,
  onTheme,
  onRefresh,
}: {
  pages: Page[];
  query: string;
  setQuery: (value: string) => void;
  admin: boolean;
  navigate: (key: string) => void;
  onDevice: (row: Row) => void;
  onVLAN: (row: Row) => void;
  onSettings: (section: string) => void;
  onTheme: () => void;
  onRefresh: () => void;
}) {
  const results = useRef<HTMLDivElement>(null);
  const words = normalized(query).trim().split(/\s+/).filter(Boolean);
  const matches = (text: string) =>
    words.every((word) => normalized(text).includes(word));
  const devices = useLiveQuery<{ items: Row[] }>(
    query.trim().length >= 2
      ? `/inventory/devices?limit=8&q=${encodeURIComponent(query.trim())}`
      : null,
    0,
    undefined,
    200,
  );
  const vlans = useLiveQuery<{ items: Row[] }>(
    query.trim().length >= 2
      ? `/vlans?limit=8&q=${encodeURIComponent(query.trim())}`
      : null,
    0,
    undefined,
    200,
  );
  const menus = pages.filter(
    (p) =>
      (admin || !["audit", "users"].includes(p.key)) &&
      matches(
        [
          p.title,
          p.group,
          p.desc,
          aliases[p.key] || "",
          ...(p.fields || []).map((f) => f.label),
        ].join(" "),
      ),
  );
  const actions = [
    {
      key: "platform",
      title: "Platform durumu",
      hint: "Sistem odası · Veritabanı, Redis, worker ve zamanlayıcı",
      icon: GearSix,
      run: () => onSettings("platform"),
    },
    {
      key: "password",
      title: "Parolamı değiştir",
      hint: "Sistem odası · Hesap ve şifre ayarları",
      icon: Key,
      run: () => onSettings("password"),
    },
    {
      key: "institutions",
      title: "Kurumlar",
      hint: "Lokasyon · Kurum ve yerleşim ayarları",
      icon: Buildings,
      run: () => navigate("sites"),
    },
    {
      key: "theme",
      title: "Temayı değiştir",
      hint: "Görünüm · Açık / koyu tema",
      icon: Sun,
      run: onTheme,
    },
    {
      key: "refresh",
      title: "Açık sayfayı yenile",
      hint: "Güncel verileri yeniden oku",
      icon: ArrowsClockwise,
      run: onRefresh,
    },
  ].filter((action) => matches(action.title + " " + action.hint));
  const deviceRows = devices.data?.items || [],
    vlanRows = vlans.data?.items || [];
  const loading = devices.loading || vlans.loading;
  const error = devices.error || vlans.error;
  const count =
    menus.length + actions.length + deviceRows.length + vlanRows.length;
  return (
    <div className="command-body">
      <label className="command-input">
        <MagnifyingGlass size={21} aria-hidden="true" />
        <input
          autoFocus
          name="workspace-search"
          autoComplete="off"
          spellCheck={false}
          maxLength={120}
          placeholder="Menü, ayar, cihaz veya VLAN ara…"
          aria-label="Menü, ayar, cihaz veya VLAN ara"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (!["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) return;
            const buttons =
              results.current?.querySelectorAll<HTMLButtonElement>("button");
            if (!buttons?.length) return;
            e.preventDefault();
            if (e.key === "Enter") buttons[0].click();
            else buttons[e.key === "ArrowUp" ? buttons.length - 1 : 0].focus();
          }}
        />
      </label>
      <div
        className="command-results"
        ref={results}
        aria-label="Arama kısayolları"
        onKeyDown={(e) => {
          if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
          const buttons = [
            ...(results.current?.querySelectorAll<HTMLButtonElement>(
              "button",
            ) || []),
          ];
          const index = buttons.indexOf(e.target as HTMLButtonElement);
          if (index < 0) return;
          e.preventDefault();
          const next =
            e.key === "Home"
              ? 0
              : e.key === "End"
                ? buttons.length - 1
                : (index + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) %
                  buttons.length;
          buttons[next].focus();
        }}
      >
        {!!actions.length && (
          <section aria-label="Ayarlar ve işlemler">
            <h3>Ayarlar ve işlemler</h3>
            {actions.map((a) => (
              <button key={a.key} onClick={a.run}>
                <a.icon size={20} aria-hidden="true" />
                <span>
                  <b>{a.title}</b>
                  <small>{a.hint}</small>
                </span>
                <ArrowUpRight size={16} aria-hidden="true" />
              </button>
            ))}
          </section>
        )}
        {!!menus.length && (
          <section aria-label="Tüm menüler">
            <h3>
              Menüler <span>{menus.length}</span>
            </h3>
            {menus.map((p) => (
              <button key={p.key} onClick={() => navigate(p.key)}>
                <p.icon size={20} aria-hidden="true" />
                <span>
                  <b>{p.title}</b>
                  <small>{p.group}</small>
                </span>
                <ArrowUpRight size={16} aria-hidden="true" />
              </button>
            ))}
          </section>
        )}
        {!!deviceRows.length && (
          <section aria-label="Cihaz sonuçları">
            <h3>Cihazlar</h3>
            {deviceRows.map((d) => (
              <button key={d.id} onClick={() => onDevice(d)}>
                <Stack size={20} aria-hidden="true" />
                <span>
                  <b>{d.name}</b>
                  <small>{d.management_ip}</small>
                </span>
                <ArrowUpRight size={16} aria-hidden="true" />
              </button>
            ))}
          </section>
        )}
        {!!vlanRows.length && (
          <section aria-label="VLAN sonuçları">
            <h3>VLAN’lar</h3>
            {vlanRows.map((v) => (
              <button key={v.id} onClick={() => onVLAN(v)}>
                <GlobeHemisphereWest size={20} aria-hidden="true" />
                <span>
                  <b>
                    VLAN-{v.vid} / {v.name}
                  </b>
                  <small>{v.cidr}</small>
                </span>
                <ArrowUpRight size={16} aria-hidden="true" />
              </button>
            ))}
          </section>
        )}
      </div>
      {loading && (
        <p className="command-status" role="status">
          Cihazlar ve VLAN’lar aranıyor…
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!count && !loading && !error && (
        <p className="command-status" role="status">
          Eşleşen menü, ayar, cihaz veya VLAN bulunamadı.
        </p>
      )}
    </div>
  );
}
