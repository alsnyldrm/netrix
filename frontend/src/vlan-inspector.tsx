import { useState } from "react";
import { CaretLeft, CaretRight, MagnifyingGlass } from "@phosphor-icons/react";
import { Dialog } from "./main";
import { useLiveQuery } from "./data";
import { AddressDetail, useIPAMUpdates } from "./ipam";
import { canOperate } from "./permissions";
import "./vlan-inspector.css";

type Row = Record<string, any>;
export function VLANInspector({
  vlan,
  user,
  onClose,
  onCreate,
}: {
  vlan: Row;
  user: Row;
  onClose: () => void;
  onCreate: (address: string) => void;
}) {
  const id = vlan.id;
  const [offset, setOffset] = useState("0");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<Row | null>(null);
  const revision = useIPAMUpdates(id);
  const grid = useLiveQuery<Row>(
    vlan.cidr && !detail
      ? `/ipam/vlans/${id}/inspection?offset=${offset}&address=${encodeURIComponent(search)}`
      : null,
    revision,
  );
  const data = grid.data;
  if (detail)
    return (
      <AddressDetail row={detail} user={user} close={() => setDetail(null)} />
    );
  return (
    <Dialog title="VLAN incele" onClose={onClose} wide>
      <div className="vlan-inspector">
        <div className="vlan-inspector-tools">
          <div className="vlan-inspector-context">
            <span>VLAN</span>
            <strong>{`VLAN-${vlan.vid} / ${vlan.name} | ${vlan.cidr}`}</strong>
          </div>
          <form
            className="vlan-inspector-search"
            onSubmit={(e) => {
              e.preventDefault();
              setSearch(query);
              setOffset("0");
            }}
          >
            <label htmlFor="inspector-ip">IP adresine git</label>
            <div>
              <input
                id="inspector-ip"
                name="address"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                placeholder={vlan.cidr.split("/")[0]}
              />
              <button
                type="submit"
                className="secondary"
                aria-label="IP adresine git"
              >
                <MagnifyingGlass size={18} aria-hidden="true" />
              </button>
            </div>
          </form>
        </div>
        <div className="vlan-inspector-legend" aria-label="IP durumları">
          <span className="inspector-free">
            ○ Boş <b>{data?.free ?? "—"}</b>
          </span>
          <span className="inspector-occupied">
            ● Dolu <b>{data?.occupied ?? "—"}</b>
          </span>
          <small>Bu görünümdeki adresler</small>
        </div>
        {grid.error && (
          <div className="error" role="alert">
            {grid.error}
          </div>
        )}
        {grid.loading && <p role="status">IP adresleri yükleniyor…</p>}
        {!!data?.items?.length && (
          <>
            <p className="vlan-inspector-range" aria-live="polite">
              <strong>
                {data.items[0].address} –{" "}
                {data.items[data.items.length - 1].address}
              </strong>
              <span>
                {data.items.length} / {data.capacity} adres
              </span>
            </p>
            <div
              className="vlan-address-grid"
              role="group"
              aria-label="VLAN IP adresleri"
            >
              {data.items.map((item: Row) => (
                <button
                  type="button"
                  key={item.address}
                  className={`vlan-address-tile ${item.state === "free" ? "inspector-free" : "inspector-occupied"}`}
                  aria-label={`${item.address} · ${item.state === "free" ? "Boş · IP ekle" : "Dolu · IP ayrıntıları"}`}
                  title={`${item.address} · ${item.state === "free" ? "Boş" : "Dolu"}`}
                  disabled={item.state === "free" && !canOperate(user)}
                  onClick={() =>
                    item.state === "free"
                      ? onCreate(item.address)
                      : setDetail({ ...item, vlan_id: id })
                  }
                >
                  <span aria-hidden="true">
                    {item.state === "free" ? "○" : "●"}
                  </span>
                  <b>
                    {item.address.includes(":")
                      ? item.address.split(":").pop() || "0"
                      : "." + item.address.split(".").pop()}
                  </b>
                </button>
              ))}
            </div>
            <div className="vlan-inspector-pages">
              <button
                className="secondary"
                disabled={!data.previous_offset}
                onClick={() => {
                  setSearch("");
                  setOffset(data.previous_offset);
                }}
              >
                <CaretLeft size={16} aria-hidden="true" /> Önceki
              </button>
              <button
                className="secondary"
                disabled={!data.next_offset}
                onClick={() => {
                  setSearch("");
                  setOffset(data.next_offset);
                }}
              >
                Sonraki <CaretRight size={16} aria-hidden="true" />
              </button>
            </div>
          </>
        )}
      </div>
    </Dialog>
  );
}
