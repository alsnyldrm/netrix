import {
  Children,
  Fragment,
  cloneElement,
  isValidElement,
  useRef,
  useState,
} from "react";
import type { ComponentProps, ReactElement, ReactNode } from "react";
import { ArrowLeft, ArrowRight, DotsSixVertical } from "@phosphor-icons/react";
import "./column-table.css";

type TableChild = ReactElement<{
  children?: ReactNode;
  colSpan?: number;
  rowSpan?: number;
  "data-column-fixed"?: boolean;
  "data-column-id"?: string;
  "aria-label"?: string;
}>;

function elements(children: ReactNode): TableChild[] {
  return Children.toArray(children).flatMap((child) => {
    if (!isValidElement(child)) return [];
    const element = child as TableChild;
    return element.type === Fragment
      ? elements(element.props.children).map((nested) =>
          cloneElement(nested, { key: `${element.key}/${nested.key}` }),
        )
      : [element];
  });
}

function label(content: ReactNode): string {
  if (typeof content === "string" || typeof content === "number")
    return String(content);
  if (isValidElement(content))
    return label((content as TableChild).props.children);
  if (Array.isArray(content)) return content.map(label).join("");
  return "";
}

function readOrder(storageKey: string): string[] {
  try {
    const stored: unknown = JSON.parse(
      localStorage.getItem(storageKey) || "[]",
    );
    return Array.isArray(stored)
      ? stored.filter((id) => typeof id === "string")
      : [];
  } catch {
    return [];
  }
}

type Props = ComponentProps<"table"> & { orderKey: string };

export function ColumnTable(props: Props) {
  return <OrderedTable key={props.orderKey} {...props} />;
}

function OrderedTable({ orderKey, children, ...props }: Props) {
  const storageKey = "netrix-column-order:" + orderKey;
  const [saved, setSaved] = useState(() => readOrder(storageKey));
  const [dragged, setDragged] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const table = useRef<HTMLTableElement>(null);
  const sections = elements(children);
  const head = sections.find((section) => section.type === "thead");
  const headRow = elements(head?.props.children)[0];
  const headers = elements(headRow?.props.children);
  const columns = headers.map((header, index) => {
    const name =
      header.props["aria-label"] || label(header.props.children).trim();
    return {
      id: header.props["data-column-id"] || name,
      name,
      index,
      fixed: header.props["data-column-fixed"] || !name,
    };
  });
  const movable = columns.filter((column) => !column.fixed);
  const visibleIds = movable.map((column) => column.id);
  const order = [...new Set([...saved, ...visibleIds])];
  const visible = order.filter((id) => visibleIds.includes(id));
  if (new Set(visibleIds).size !== movable.length || movable.length < 2)
    return <table {...props}>{children}</table>;
  const indices = columns.map((column, index) =>
    column.fixed
      ? index
      : movable.find((item) => item.id === visible[movable.indexOf(column)])!
          .index,
  );

  const clearDrag = () => {
    setDragged(null);
    setTarget(null);
  };

  const move = (source: string, destination: string) => {
    if (source === destination) return;
    const next = [...visible];
    const start = next.indexOf(source);
    const end = next.indexOf(destination);
    if (start === -1 || end === -1) return;
    next.splice(start, 1);
    next.splice(end, 0, source);
    let index = 0;
    const updated = order.map((id) =>
      visibleIds.includes(id) ? next[index++] : id,
    );
    setSaved(updated);
    try {
      localStorage.setItem(storageKey, JSON.stringify(updated));
    } catch {
      // Ordering still works for the current view if storage is unavailable.
    }
    setAnnouncement(
      `${movable.find((column) => column.id === source)?.name}, ${end + 1}. sütuna taşındı.`,
    );
  };

  const renderHeader = (index: number) => {
    const header = headers[index];
    const { id, name, fixed } = columns[index];
    if (fixed) return header;
    const position = visible.indexOf(id);
    const left = visible[position - 1];
    const right = visible[position + 1];
    const menu = (direction: string, adjacent: string | undefined) => (
      <button
        type="button"
        disabled={!adjacent}
        onClick={(event) => {
          const panel = event.currentTarget.closest<HTMLElement>("[popover]")!;
          const handle = panel.previousElementSibling as HTMLButtonElement;
          panel.hidePopover();
          if (adjacent) move(id, adjacent);
          handle.focus();
        }}
      >
        {direction === "Sola taşı" ? (
          <ArrowLeft size={16} />
        ) : (
          <ArrowRight size={16} />
        )}
        {direction}
      </button>
    );
    return (
      <th
        {...header.props}
        key={header.key}
        data-column-id={id}
        aria-label={name}
        data-column-target={target === id && dragged !== id ? "" : undefined}
        onDragOver={(event) => {
          if (!dragged) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
          setTarget(id);
          const scroller = table.current?.parentElement;
          if (!scroller) return;
          const bounds = scroller.getBoundingClientRect();
          if (event.clientX < bounds.left + 32) scroller.scrollLeft -= 16;
          else if (event.clientX > bounds.right - 32) scroller.scrollLeft += 16;
        }}
        onDrop={(event) => {
          if (!dragged) return;
          event.preventDefault();
          move(dragged, id);
          clearDrag();
        }}
      >
        <div className="column-table-heading">
          {header.props.children}
          <button
            type="button"
            className="column-table-handle"
            draggable
            aria-label={`${name} sütununu taşı`}
            title={`${name} sütununu taşı`}
            onDragStart={(event) => {
              const panel = event.currentTarget
                .nextElementSibling as HTMLElement;
              panel.hidePopover();
              event.dataTransfer.effectAllowed = "move";
              event.dataTransfer.setData("text/plain", name);
              setDragged(id);
            }}
            onDragEnd={clearDrag}
            onClick={(event) => {
              const handle = event.currentTarget;
              const panel = handle.nextElementSibling as HTMLElement;
              const bounds = handle.getBoundingClientRect();
              panel.style.left = `${Math.max(8, Math.min(bounds.right - 140, innerWidth - 148))}px`;
              panel.style.top = `${bounds.bottom + 108 > innerHeight ? bounds.top - 96 : bounds.bottom + 4}px`;
              if (panel.togglePopover())
                panel
                  .querySelector<HTMLButtonElement>("button:enabled")
                  ?.focus();
            }}
          >
            <DotsSixVertical size={16} weight="bold" aria-hidden="true" />
          </button>
          <div
            popover="auto"
            className="column-table-menu"
            role="group"
            aria-label={`${name} sütun sırası`}
          >
            {menu("Sola taşı", left)}
            {menu("Sağa taşı", right)}
          </div>
        </div>
      </th>
    );
  };

  const renderBody = (section: TableChild) => {
    let rowSpan = 0;
    return cloneElement(
      section,
      undefined,
      elements(section.props.children).map((row) => {
        const cells = elements(row.props.children);
        const offset = rowSpan > 0 ? 1 : 0;
        rowSpan = offset ? rowSpan - 1 : (cells[0]?.props.rowSpan || 1) - 1;
        if (
          cells.length + offset !== headers.length ||
          cells.some((cell) => (cell.props.colSpan || 1) > 1)
        )
          return row;
        return cloneElement(
          row,
          undefined,
          indices.slice(offset).map((index) =>
            cloneElement(cells[index - offset], {
              "data-column-id": columns[index].id,
            }),
          ),
        );
      }),
    );
  };

  return (
    <>
      <span className="column-table-announcement" role="status">
        {announcement}
      </span>
      <table {...props} ref={table}>
        {sections.map((section) => {
          if (section === head)
            return cloneElement(
              section,
              undefined,
              cloneElement(headRow, undefined, indices.map(renderHeader)),
            );
          return section.type === "tbody" ? renderBody(section) : section;
        })}
      </table>
    </>
  );
}
