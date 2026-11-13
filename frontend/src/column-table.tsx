import {
  Children,
  Fragment,
  cloneElement,
  isValidElement,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { ComponentProps, ReactElement, ReactNode } from "react";
import { flushSync } from "react-dom";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ArrowsDownUp,
  DotsSixVertical,
} from "@phosphor-icons/react";
import "./column-table.css";

type TableChild = ReactElement<{
  children?: ReactNode;
  colSpan?: number;
  rowSpan?: number;
  "data-column-fixed"?: boolean;
  "data-column-id"?: string;
  "data-column-width-key"?: string;
  "aria-label"?: string;
  "aria-sort"?: ComponentProps<"th">["aria-sort"];
  className?: string;
  value?: unknown;
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
  if (isValidElement(content)) {
    const { children, value } = (content as TableChild).props;
    return children == null &&
      (typeof value === "string" || typeof value === "number")
      ? String(value)
      : label(children);
  }
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
      parseFloat(getComputedStyle(cell).width) || cell.offsetWidth,
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

export type ColumnSort = { key: string; direction: "asc" | "desc" };
const sortCollator = new Intl.Collator("tr", {
  numeric: true,
  sensitivity: "base",
});

type Props = ComponentProps<"table"> & {
  orderKey: string;
  sort?: ColumnSort | null;
  onSortChange?: (sort: ColumnSort) => void;
};

export function ColumnTable(props: Props) {
  return <OrderedTable key={props.orderKey} {...props} />;
}

function OrderedTable({
  orderKey,
  children,
  sort,
  onSortChange,
  ...props
}: Props) {
  const [localSort, setLocalSort] = useState<ColumnSort | null>(null);
  const currentSort = onSortChange ? sort : localSort;
  const storageKey = "netrix-column-order:" + orderKey;
  const [saved, setSaved] = useState(() => readOrder(storageKey));
  const widthKey = "netrix-column-width:" + orderKey;
  const [widths, setWidths] = useState(() => readWidths(widthKey));
  const [baseWidths, setBaseWidths] = useState<Widths>({});
  const [activeResize, setActiveResize] = useState<string | null>(null);
  const resize = useRef<{
    pointer: number;
    id: string;
    x: number;
    lastX: number;
    width: number;
    preview: number;
    measured: Widths;
    total: number;
    scale: number;
    scroller: HTMLElement | null;
    lastScroll: number;
    scrollDelta: number;
    moved: boolean;
    frame: number;
    handle: HTMLElement;
    removeListeners: () => void;
  } | null>(null);
  useLayoutEffect(
    () => () => {
      const active = resize.current;
      if (!active) return;
      cancelAnimationFrame(active.frame);
      active.removeListeners();
      resize.current = null;
      document.documentElement.classList.remove("column-resizing");
    },
    [],
  );
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
    (custom || activeResize !== null) &&
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
    const next = clampWidth(width);
    flushSync(() => {
      if (!fixedLayout) setBaseWidths(measureWidths(table.current));
      saveWidth(id, next);
    });
    const name = columns.find((column) => column.widthKey === id)?.name;
    setAnnouncement(`${name} sütunu ${next} piksel.`);
  };

  const fitColumn = (header: HTMLTableCellElement) => {
    if (!table.current || !header.dataset.columnWidthKey) return;
    changeWidth(header.dataset.columnWidthKey, fitWidth(table.current, header));
  };

  const previewResize = () => {
    const active = resize.current;
    if (!active || !table.current) return;
    active.frame = 0;
    // Account for deliberate horizontal scrolling, not the browser clamping
    // scrollLeft as the table itself becomes narrower.
    const scroll = active.scroller?.scrollLeft ?? 0;
    active.scrollDelta += scroll - active.lastScroll;
    const movement =
      (active.lastX - active.x + active.scrollDelta) / active.scale;
    active.moved ||= Math.abs(movement) >= 3;
    if (!active.moved) return;
    const desired = active.width + movement;
    active.preview = clampWidth(desired);
    // Once a limit is reached, reversing the pointer must respond immediately.
    if (desired < MIN_WIDTH || desired > MAX_WIDTH)
      active.x =
        active.lastX +
        active.scrollDelta -
        (active.preview - active.width) * active.scale;
    const col = Array.from(table.current.querySelectorAll("col")).find(
      (el) => el.dataset.columnWidthKey === active.id,
    );
    if (!col) return;
    // Update only the colgroup per frame, not every React row on every event.
    col.style.width = `${active.preview}px`;
    table.current.style.width = `${active.total + active.preview - active.width}px`;
    active.lastScroll = active.scroller?.scrollLeft ?? 0;
  };

  const finishResize = (save: boolean) => {
    const active = resize.current;
    if (!active) return;
    cancelAnimationFrame(active.frame);
    if (save) previewResize();
    const finalWidth = save && active.moved ? active.preview : active.width;
    if (table.current) {
      table.current.querySelectorAll("col").forEach((col) => {
        const id = col.dataset.columnWidthKey!;
        col.style.width = `${id === active.id ? finalWidth : active.measured[id]}px`;
      });
      table.current.style.width = `${active.total + finalWidth - active.width}px`;
    }
    resize.current = null;
    active.removeListeners();
    document.documentElement.classList.remove("column-resizing");
    if (active.handle.hasPointerCapture(active.pointer))
      active.handle.releasePointerCapture(active.pointer);
    flushSync(() => {
      if (save && active.moved) saveWidth(active.id, finalWidth);
      setActiveResize(null);
    });
    if (save && active.moved) {
      const name = columns.find(
        (column) => column.widthKey === active.id,
      )?.name;
      setAnnouncement(`${name} sütunu ${finalWidth} piksel.`);
    }
  };

  // Both hit areas at a shared boundary resize the same column to its left.
  // Keep each half inside its sticky cell so the next header cannot cover it.
  const resizeHandle = (id: string, name: string, side: "left" | "right") => (
    <span
      className={`column-table-resize column-table-resize-${side}`}
      data-column-resizing={activeResize === id || undefined}
      aria-hidden="true"
      title={`${name} · Sürükleyerek genişliği ayarlayın, çift tıklayarak içeriğe sığdırın`}
      onPointerDown={(event) => {
        if (
          event.button !== 0 ||
          !event.isPrimary ||
          resize.current ||
          !table.current
        )
          return;
        event.preventDefault();
        event.stopPropagation();
        const handle = event.currentTarget;
        const measured = measureWidths(table.current);
        const width = measured[id];
        if (!width) return;
        const scroller =
          table.current.closest<HTMLElement>(".table-scroll") ??
          table.current.parentElement;
        const escape = (e: KeyboardEvent) => {
          if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            finishResize(false);
          }
        };
        const blur = () => finishResize(false);
        resize.current = {
          pointer: event.pointerId,
          id,
          x: event.clientX,
          lastX: event.clientX,
          width,
          preview: width,
          measured,
          total: Object.values(measured).reduce((sum, value) => sum + value, 0),
          scale:
            table.current.getBoundingClientRect().width /
              table.current.offsetWidth || 1,
          scroller,
          lastScroll: scroller?.scrollLeft ?? 0,
          scrollDelta: 0,
          moved: false,
          frame: 0,
          handle,
          removeListeners: () => {
            window.removeEventListener("keydown", escape, true);
            window.removeEventListener("blur", blur);
          },
        };
        flushSync(() => {
          setBaseWidths(measured);
          setActiveResize(id);
        });
        handle.setPointerCapture(event.pointerId);
        document.documentElement.classList.add("column-resizing");
        window.addEventListener("keydown", escape, true);
        window.addEventListener("blur", blur);
      }}
      onPointerMove={(event) => {
        const active = resize.current;
        if (!active || event.pointerId !== active.pointer) return;
        event.preventDefault();
        event.stopPropagation();
        active.lastX = event.clientX;
        if (!active.frame) active.frame = requestAnimationFrame(previewResize);
      }}
      onPointerUp={(event) => {
        const active = resize.current;
        if (!active || active.pointer !== event.pointerId) return;
        event.stopPropagation();
        active.lastX = event.clientX;
        finishResize(true);
      }}
      onPointerCancel={() => finishResize(false)}
      onLostPointerCapture={() => finishResize(false)}
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        const header = Array.from(
          table.current?.tHead?.rows[0]?.cells || [],
        ).find((cell) => cell.dataset.columnWidthKey === id);
        if (header) fitColumn(header);
      }}
    />
  );

  const renderHeader = (index: number) => {
    const header = headers[index];
    const { id, name, fixed, widthKey } = columns[index];
    const previous = columns[indices[indices.indexOf(index) - 1]];
    const leftEdge =
      previous && !previous.fixed
        ? resizeHandle(previous.widthKey, previous.name, "left")
        : null;
    if (fixed)
      return cloneElement(
        header,
        { "data-column-width-key": widthKey },
        <>
          {leftEdge}
          {header.props.children}
        </>,
      );
    const nativeSort = elements(header.props.children).some((child) =>
      child.props.className?.split(" ").includes("column-sort"),
    );
    const direction =
      currentSort?.key === id ? currentSort.direction : undefined;
    const SortIcon =
      direction === "asc"
        ? ArrowUp
        : direction === "desc"
          ? ArrowDown
          : ArrowsDownUp;
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
        data-column-resizing={activeResize === widthKey || undefined}
        aria-label={name}
        aria-sort={
          nativeSort
            ? header.props["aria-sort"]
            : direction === "asc"
              ? "ascending"
              : direction === "desc"
                ? "descending"
                : undefined
        }
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
        {leftEdge}
        {resizeHandle(widthKey, name, "right")}
        <div className="column-table-heading">
          <span className="column-table-label" title={name}>
            {nativeSort ? (
              header.props.children
            ) : (
              <button
                type="button"
                className="column-sort column-table-sort"
                aria-label={`${name}: ${direction === "asc" ? "azalan" : "artan"} sırala`}
                onClick={() =>
                  (onSortChange ?? setLocalSort)({
                    key: id,
                    direction: direction === "asc" ? "desc" : "asc",
                  })
                }
              >
                <span>{header.props.children}</span>
                <SortIcon size={14} aria-hidden="true" />
              </button>
            )}
          </span>
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
    let rows = elements(section.props.children);
    const sortIndex = columns.findIndex(
      (column) => column.id === localSort?.key,
    );
    if (!onSortChange && localSort && sortIndex >= 0) {
      const first = elements(rows[0]?.props.children)[0];
      const groupHeader =
        first?.props.rowSpan === rows.length && rows.length > 1 ? first : null;
      const entries = rows.map((row, index) => ({
        row,
        cells: elements(row.props.children).slice(
          groupHeader && index === 0 ? 1 : 0,
        ),
      }));
      const offset = groupHeader ? 1 : 0;
      if (
        sortIndex >= offset &&
        entries.every(
          ({ cells }) =>
            cells.length + offset === headers.length &&
            cells.every((cell) => !cell.props.rowSpan && !cell.props.colSpan),
        )
      ) {
        const value = (cells: TableChild[]) =>
          label(cells[sortIndex - offset].props.children).trim();
        const order = localSort.direction === "asc" ? 1 : -1;
        entries.sort(
          (a, b) =>
            order * sortCollator.compare(value(a.cells), value(b.cells)),
        );
        rows = entries.map(({ row, cells }, index) =>
          cloneElement(
            row,
            undefined,
            groupHeader && index === 0 ? [groupHeader, ...cells] : cells,
          ),
        );
      }
    }
    let rowSpan = 0;
    return cloneElement(
      section,
      undefined,
      rows.map((row) => {
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
        if (activeResize && resize.current)
          return key === resize.current.id
            ? resize.current.preview
            : resize.current.measured[key];
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
              <col
                key={columns[indices[index]].widthKey}
                data-column-width-key={columns[indices[index]].widthKey}
                style={{ width }}
              />
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
