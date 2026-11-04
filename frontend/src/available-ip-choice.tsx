import { useEffect, useState } from "react";
import { api } from "./data";
import { SearchableChoice } from "./searchable-choice";
import "./available-ip-choice.css";

/** Paginated, searchable SQL-only choices; the server checks vacancy again on save. */
export function AvailableIPChoice({
  vlanId,
  value,
  onChange,
}: {
  vlanId: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState("0");
  const [options, setOptions] = useState<{ value: string; label: string }[]>(
    [],
  );
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, retry] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(
      () => {
        api(
          `/ipam/vlans/${vlanId}/available-addresses?offset=${offset}&q=${encodeURIComponent(query)}&limit=100`,
        )
          .then((data) => {
            if (!active) return;
            const found = data.items.map((item: { address: string }) => ({
              value: item.address,
              label: item.address,
            }));
            setOptions((current) =>
              offset === "0" ? found : [...current, ...found],
            );
            setNext(data.next_offset);
          })
          .catch((e: Error) => {
            if (active) {
              setError(e.message);
              setNext(null);
            }
          })
          .finally(() => {
            if (active) setLoading(false);
          });
      },
      query ? 200 : 0,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [vlanId, query, offset, revision]);
  return (
    <>
      <SearchableChoice
        inputId="choice-address"
        label="IP adresi"
        value={value}
        required
        loading={loading}
        showSelectedPath={false}
        footer={
          (next || error) && (
            <button
              type="button"
              className="text-button"
              disabled={loading}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => (error ? retry((v) => v + 1) : setOffset(next!))}
            >
              {error ? "Yeniden dene" : "Daha fazla IP"}
            </button>
          )
        }
        options={
          value && !options.some((o) => o.value === value)
            ? [{ value, label: value }, ...options]
            : options
        }
        onSearch={(q, typing) => {
          if (typing) onChange("");
          if (q !== query) {
            setQuery(q);
            setOffset("0");
          }
        }}
        onChange={onChange}
      />
      <div className="available-ip-actions">
        <span className="muted" role={error ? "alert" : "status"}>
          {loading
            ? "Boş IP’ler yükleniyor…"
            : error
              ? error
              : !options.length
                ? "Boş IP bulunamadı."
                : `${options.length} boş IP listeleniyor`}
        </span>
      </div>
    </>
  );
}
