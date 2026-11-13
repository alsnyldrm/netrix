import {
  Children,
  Fragment,
  cloneElement,
  isValidElement,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type {
  ComponentProps,
  PointerEvent,
  ReactElement,
  ReactNode,
} from "react";
import { ArrowLeft, ArrowRight, DotsSixVertical } from "@phosphor-icons/react";
import "./column-table.css";

type TableChild = ReactElement<{
  children?: ReactNode;
  colSpan?: number;
  rowSpan?: number;
  "data-column-fixed"?: boolean;
  "data-column-id"?: string;
  "data-column-width-key"?: string;
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

const MIN_WIDTH = 96;
const MAX_WIDTH = 1600;
const WIDTH_STEP = 24;
type Widths = Record<string, number>;

function readWidths(key: string): Widths {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(key) || "{}");
    if (!stored || typeof stored !== "object" || Array.isArray(stored))
      return {};
    return Object.fromEntries(
      Object.entries(stored).filter(
        ([, width]) =>
          typeof width === "number" && width >= MIN_WIDTH && width <= MAX_WIDTH,
      ),
    );
  } catch {
    return {};
  }
}

function measureWidths(table: HTMLTableElement | null): Widths {
  return Object.fromEntries(
    Array.from(table?.tHead?.rows[0]?.cells || []).map((cell) => [
      cell.dataset.columnWidthKey!,
      cell.getBoundingClientRect().width,
    ]),
  );
}

function clampWidth(width: number) {
  return Math.round(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, width)));
}

function fitWidth(table: HTMLTableElement, header: HTMLTableCellElement) {
  const probe = table.cloneNode(false) as HTMLTableElement;
  probe.removeAttribute("id");
  probe.removeAttribute("data-column-layout");
  probe.setAttribute("aria-hidden", "true");
  probe.classList.add("column-table-measure");
  probe.inert = true;

  for (const section of [table.tHead, ...Array.from(table.tBodies)]) {
    if (!section) continue;
    const copy = section.cloneNode(false) as HTMLTableSectionElement;
    copy.removeAttribute("id");
    for (const row of Array.from(section.rows)) {
      const cell = Array.from(row.cells).find(
        (item) =>
          item === header || item.dataset.columnId === header.dataset.columnId,
      );
      if (!cell || cell.colSpan !== 1) continue;
      const content = cell.cloneNode(true) as HTMLTableCellElement;
      content.rowSpan = 1;
      content.removeAttribute("id");
      content
        .querySelectorAll("[id]")
        .forEach((element) => element.removeAttribute("id"));
      content
        .querySelectorAll("[popover], .column-table-resize")
        .forEach((element) => element.remove());
      copy.insertRow().append(content);
    }
    probe.append(copy);
  }

  table.after(probe);
  try {
    return Math.ceil(probe.getBoundingClientRect().width);
  } finally {
    probe.remove();
  }
}

type Props = ComponentProps<"table"> & { orderKey: string };

export function ColumnTable(props: Props) {
  return <OrderedTable key={props.orderKey} {...props} />;
}

function OrderedTable({ orderKey, children, ...props }: Props) {
  const storageKey = "netrix-column-order:" + orderKey;
  const [saved, setSaved] = useState(() => readOrder(storageKey));
  const widthKey = "netrix-column-width:" + orderKey;
  const [widths, setWidths] = useState(() => readWidths(widthKey));
  const [baseWidths, setBaseWidths] = useState<Widths>({});
  const [activeResize, setActiveResize] = useState<{
    id: string;
    side: "left" | "right";
  } | null>(null);
  const guide = useRef<HTMLSpanElement>(null);
  const resize = useRef<{
    pointer: number;
    x: number;
    width: number;
    direction: number;
    scrollLeft: number;
  } | null>(null);
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
      widthKey: name
        ? `named:${header.props["data-column-id"] || name}`
        : `fixed:${index}`,
      fixed: header.props["data-column-fixed"] || !name,
    };
  });
  const movable = columns.filter((column) => !column.fixed);
  const visibleIds = movable.map((column) => column.id);
  const order = [...new Set([...saved, ...visibleIds])];
  const visible = order.filter((id) => visibleIds.includes(id));
  const supported =
    new Set(visibleIds).size === movable.length && movable.length > 0;
  const custom = columns.some(
    (column) => !column.fixed && Object.hasOwn(widths, column.widthKey),
  );
  const fixedLayout =
    supported &&
    custom &&
    columns.every((column) => Object.hasOwn(baseWidths, column.widthKey));
  useLayoutEffect(() => {
    if (supported && custom && !fixedLayout) {
      const measured = measureWidths(table.current);
      if (Object.values(measured).every((width) => width > 0))
        setBaseWidths(measured);
    }
  }, [supported, custom, fixedLayout, children]);
  if (!supported) return <table {...props}>{children}</table>;
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

  const saveWidth = (id: string, width?: number) => {
    const updated = { ...widths };
    if (width === undefined) delete updated[id];
    else updated[id] = width;
    setWidths(updated);
    try {
      localStorage.setItem(widthKey, JSON.stringify(updated));
    } catch {
      // The width remains available for the current view.
    }
  };

  const changeWidth = (id: string, width: number) => {
    if (!fixedLayout) setBaseWidths(measureWidths(table.current));
    const next = clampWidth(width);
    saveWidth(id, next);
    const name = columns.find((column) => column.widthKey === id)?.name;
    setAnnouncement(`${name} sütunu ${next} piksel.`);
  };

  const fitColumn = (header: HTMLTableCellElement) => {
    if (!table.current || !header.dataset.columnWidthKey) return;
    changeWidth(header.dataset.columnWidthKey, fitWidth(table.current, header));
  };

  const resizeHandle = (id: string, name: string, side: "left" | "right") => {
    const activeEdge = activeResize?.id === id && activeResize.side === side;
    const delta = (
      event: PointerEvent<HTMLSpanElement>,
      active: NonNullable<typeof resize.current>,
    ) =>
      event.clientX -
      active.x +
      (table.current?.parentElement?.scrollLeft ?? 0) -
      active.scrollLeft;
    const cancel = (event: PointerEvent<HTMLSpanElement>) => {
      if (resize.current?.pointer !== event.pointerId) return;
      resize.current = null;
      setActiveResize(null);
    };
    return (
      <span
        className={`column-table-resize column-table-resize-${side}`}
        aria-hidden="true"
        title={`${name} · Sürükleyerek genişliği ayarlayın, çift tıklayarak içeriğe sığdırın`}
        onPointerDown={(event) => {
          if (event.button !== 0 || !event.isPrimary || resize.current) return;
          const width = event.currentTarget
            .closest("th")!
            .getBoundingClientRect().width;
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          resize.current = {
            pointer: event.pointerId,
            x: event.clientX,
            direction: side === "left" ? -1 : 1,
            width,
            scrollLeft: table.current?.parentElement?.scrollLeft ?? 0,
          };
          setActiveResize({ id, side });
        }}
        onPointerMove={(event) => {
          const active = resize.current;
          if (!active || event.pointerId !== active.pointer || !guide.current)
            return;
          const width = clampWidth(
            active.width + delta(event, active) * active.direction,
          );
          guide.current.style.transform = `translateX(${(width - active.width) * active.direction}px)`;
        }}
        onPointerUp={(event) => {
          const active = resize.current;
          if (!active || active.pointer !== event.pointerId) return;
          const movement = delta(event, active);
          if (Math.abs(movement) >= 3)
            changeWidth(id, active.width + movement * active.direction);
          cancel(event);
        }}
        onPointerCancel={cancel}
        onLostPointerCapture={cancel}
        onDoubleClick={(event) => {
          event.preventDefault();
          fitColumn(event.currentTarget.closest("th")!);
        }}
      >
        {activeEdge && (
          <span className="column-table-resize-guide" ref={guide} />
        )}
      </span>
    );
  };

  const renderHeader = (index: number) => {
    const header = headers[index];
    const { id, name, fixed, widthKey } = columns[index];
    if (fixed)
      return cloneElement(header, { "data-column-width-key": widthKey });
    const resizeFromMenu =
      (step?: number) => (event: React.MouseEvent<HTMLButtonElement>) => {
        const header = event.currentTarget.closest("th")!;
        if (step === undefined) {
          saveWidth(widthKey);
          setAnnouncement("Varsayılan sütun genişliği geri yüklendi.");
        } else {
          changeWidth(widthKey, header.getBoundingClientRect().width + step);
        }
      };
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
        data-column-width-key={widthKey}
        data-column-resizing={activeResize?.id === widthKey || undefined}
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
        {resizeHandle(widthKey, name, "left")}
        {resizeHandle(widthKey, name, "right")}
        <div className="column-table-heading">
          <span className="column-table-label">{header.props.children}</span>
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
              if (!panel.togglePopover()) return;
              const { offsetWidth, offsetHeight } = panel;
              panel.style.left = `${Math.max(8, Math.min(bounds.right - offsetWidth, innerWidth - offsetWidth - 8))}px`;
              panel.style.top = `${Math.max(8, bounds.bottom + offsetHeight + 12 > innerHeight ? bounds.top - offsetHeight - 4 : bounds.bottom + 4)}px`;
              panel.querySelector<HTMLButtonElement>("button:enabled")?.focus();
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
            <button type="button" onClick={resizeFromMenu(-WIDTH_STEP)}>
              Daralt
            </button>
            <button type="button" onClick={resizeFromMenu(WIDTH_STEP)}>
              Genişlet
            </button>
            <button
              type="button"
              onClick={(event) => fitColumn(event.currentTarget.closest("th")!)}
            >
              İçeriğe sığdır
            </button>
            <button
              type="button"
              disabled={!Object.hasOwn(widths, widthKey)}
              onClick={resizeFromMenu()}
            >
              Genişliği sıfırla
            </button>
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

  const layout = fixedLayout
    ? indices.map((index) => {
        const column = columns[index];
        const key = column.widthKey;
        return Object.hasOwn(widths, key) ? widths[key] : baseWidths[key];
      })
    : null;

  return (
    <>
      <span className="column-table-announcement" role="status">
        {announcement}
      </span>
      <table
        {...props}
        ref={table}
        data-column-layout={layout ? "fixed" : undefined}
        style={
          layout
            ? {
                ...props.style,
                width: layout.reduce((total, width) => total + width, 0),
              }
            : props.style
        }
      >
        {layout && (
          <colgroup>
            {layout.map((width, index) => (
              <col key={columns[indices[index]].widthKey} style={{ width }} />
            ))}
          </colgroup>
        )}
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
