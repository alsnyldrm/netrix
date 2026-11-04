import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { CaretDown, Check } from "@phosphor-icons/react";
import "./searchable-choice.css";

type Choice = { value: string; label: string };
const normalized = (s: string) =>
  s.toLocaleLowerCase("tr").replaceAll("ı", "i");

/** Filter an existing selection without committing typed, unselected text. */
export function SearchableChoice({
  inputId,
  label,
  value,
  options,
  onChange,
  disabled = false,
  required = false,
  onSearch,
  loading = false,
  showSelectedPath = true,
  footer,
}: {
  inputId?: string;
  label: string;
  value: string;
  options: Choice[];
  onChange: (value: string) => void;
  disabled?: boolean;
  required?: boolean;
  onSearch?: (query: string, typing?: boolean) => void;
  loading?: boolean;
  showSelectedPath?: boolean;
  footer?: ReactNode;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const [menu, setMenu] = useState({ above: false, height: 240 });
  const selected = options.find((o) => o.value === value);
  const words = normalized(query).split(/\s+/).filter(Boolean);
  const filtered = options.filter((o) =>
    words.every((w) => normalized(o.label).includes(w)),
  );
  const expanded = open && !disabled;
  const hasFooter = !!footer;
  useLayoutEffect(() => {
    if (!expanded || !input.current) return;
    const dialog = input.current.closest("dialog");
    const position = () => {
      const rect = input.current!.getBoundingClientRect();
      const frame = dialog?.getBoundingClientRect();
      const header = dialog
        ?.querySelector(".dialog-header")
        ?.getBoundingClientRect();
      const top = Math.max(8, header?.bottom ?? frame?.top ?? 8);
      const bottom = Math.min(
        window.innerHeight - 8,
        frame?.bottom ?? window.innerHeight - 8,
      );
      const below = bottom - rect.bottom - 8,
        above = rect.top - top - 8;
      const flip = below < 180 && above > below;
      setMenu({
        above: flip,
        height: Math.max(
          44,
          Math.min(240, (flip ? above : below) - (hasFooter ? 48 : 0) - 8),
        ),
      });
    };
    position();
    window.addEventListener("resize", position);
    dialog?.addEventListener("scroll", position);
    return () => {
      window.removeEventListener("resize", position);
      dialog?.removeEventListener("scroll", position);
    };
  }, [expanded, hasFooter]);
  const choose = (choice: Choice) => {
    onChange(choice.value);
    setOpen(false);
    setQuery("");
    setActive(-1);
  };
  const show = () => {
    onSearch?.("");
    setOpen(true);
    setQuery("");
    setActive(-1);
  };
  useEffect(() => {
    input.current?.setCustomValidity(
      required && !value ? `${label} seçin.` : "",
    );
  }, [required, value, label]);
  useEffect(() => {
    if (expanded && active >= 0)
      list.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [expanded, active]);
  return (
    <>
      <div
        className="searchable-choice"
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) {
            setOpen(false);
            setQuery("");
            setActive(-1);
          }
        }}
      >
        <div className="choice-control">
          <input
            ref={input}
            id={inputId || `${id}-input`}
            role="combobox"
            aria-label={label}
            name={label}
            aria-expanded={expanded}
            aria-controls={expanded ? id : undefined}
            aria-autocomplete="list"
            aria-required={required || undefined}
            aria-busy={loading || undefined}
            aria-activedescendant={
              expanded && active >= 0 && filtered[active]
                ? `${id}-${active}`
                : undefined
            }
            disabled={disabled}
            required={required}
            autoComplete="off"
            spellCheck={false}
            title={selected?.label}
            value={expanded ? query : value ? selected?.label || "" : ""}
            placeholder={expanded ? `${label} ara…` : "Seçilmedi"}
            onFocus={show}
            onClick={() => {
              if (!expanded) show();
            }}
            onChange={(e) => {
              onSearch?.(e.target.value, true);
              setQuery(e.target.value);
              setOpen(true);
              setActive(-1);
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape" && expanded) {
                e.preventDefault();
                e.stopPropagation();
                setOpen(false);
              } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                if (!expanded) show();
                const next =
                  e.key === "ArrowDown"
                    ? active + 1
                    : active < 0
                      ? filtered.length - 1
                      : active - 1;
                setActive(Math.max(0, Math.min(filtered.length - 1, next)));
              } else if (e.key === "Enter" && expanded) {
                e.preventDefault();
                if (filtered[active]) choose(filtered[active]);
              }
            }}
          />
          <CaretDown size={16} aria-hidden="true" />
          {expanded && (
            <div
              className="choice-popover"
              style={
                menu.above
                  ? {
                      top: "auto",
                      bottom: "100%",
                      marginTop: 0,
                      marginBottom: 4,
                    }
                  : undefined
              }
            >
              <ul
                ref={list}
                id={id}
                role="listbox"
                aria-label={`${label} seçenekleri`}
                style={{ maxHeight: menu.height }}
              >
                {filtered.map((choice, index) => (
                  <li
                    key={choice.value}
                    id={`${id}-${index}`}
                    role="option"
                    aria-selected={choice.value === value}
                    className={active === index ? "choice-active" : ""}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => choose(choice)}
                  >
                    <span>{choice.label}</span>
                    {choice.value === value && (
                      <Check size={16} aria-hidden="true" />
                    )}
                  </li>
                ))}
                {loading && (
                  <li role="presentation" className="choice-empty">
                    <span role="status">Seçenekler yükleniyor…</span>
                  </li>
                )}
                {!loading && !filtered.length && (
                  <li role="presentation" className="choice-empty">
                    Eşleşen kayıt yok.
                  </li>
                )}
              </ul>
              {footer && <div className="choice-footer">{footer}</div>}
            </div>
          )}
        </div>
      </div>
      {showSelectedPath && selected?.value && (
        <small className="choice-selected-path">{selected.label}</small>
      )}
    </>
  );
}
