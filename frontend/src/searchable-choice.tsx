import { useEffect, useId, useRef, useState } from "react";
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
}: {
  inputId?: string;
  label: string;
  value: string;
  options: Choice[];
  onChange: (value: string) => void;
  disabled?: boolean;
  required?: boolean;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const selected = options.find((o) => o.value === value);
  const words = normalized(query).split(/\s+/).filter(Boolean);
  const filtered = options.filter((o) =>
    words.every((w) => normalized(o.label).includes(w)),
  );
  const expanded = open && !disabled;
  const choose = (choice: Choice) => {
    onChange(choice.value);
    setOpen(false);
    setQuery("");
    setActive(-1);
  };
  const show = () => {
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
      <div className="searchable-choice">
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
            onBlur={() => {
              setOpen(false);
              setQuery("");
              setActive(-1);
            }}
            onChange={(e) => {
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
            <ul
              ref={list}
              id={id}
              role="listbox"
              aria-label={`${label} seçenekleri`}
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
              {!filtered.length && (
                <li role="presentation" className="choice-empty">
                  Eşleşen kayıt yok.
                </li>
              )}
            </ul>
          )}
        </div>
      </div>
      {selected?.value && (
        <small className="choice-selected-path">{selected.label}</small>
      )}
    </>
  );
}
