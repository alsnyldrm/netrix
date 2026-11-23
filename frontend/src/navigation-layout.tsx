import { useEffect, useRef, useState } from "react";
import type { ComponentType } from "react";
import { currentPreferences } from "./preferences";
import "./navigation-layout.css";

export const navigationLayouts = [
  ["left", "Sol menü", "Bölümler ve sayfalar soldaki kenar çubuğunda."],
  ["top", "Üst menü", "Bölümün üzerine gelince alt menü aşağı açılır."],
  ["right", "Sağ menü", "Bölümler ve sayfalar sağdaki kenar çubuğunda."],
  [
    "rail",
    "Simge şeridi",
    "Bölüm simgeleri solda, bölüm sayfaları içerik üstünde.",
  ],
  [
    "top-tabs",
    "İki sıralı üst menü",
    "Bölümler üst sırada, açık bölümün sayfaları hemen altında.",
  ],
] as const;
export type NavigationLayout = (typeof navigationLayouts)[number][0];

export function useNavigationLayout() {
  const [layout, setLayout] = useState(
    () => currentPreferences().navigation_layout,
  );
  useEffect(() => {
    const update = () => setLayout(currentPreferences().navigation_layout);
    window.addEventListener("netrix:preferences", update);
    return () => window.removeEventListener("netrix:preferences", update);
  }, []);
  return layout;
}

export type NavigationBadgeValue = {
  count: number;
  label: string;
  neutral?: boolean;
};
export function NavigationBadge({ value }: { value?: NavigationBadgeValue }) {
  if (!value || value.count <= 0) return null;
  return (
    <b
      className={"nav-count" + (value.neutral ? " neutral" : "")}
      aria-label={`${value.count} ${value.label}`}
    >
      {value.count}
    </b>
  );
}

type Entry = {
  badge?: NavigationBadgeValue;
  key: string;
  title: string;
  group: string;
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean }>;
};
type Props = {
  pages: Entry[];
  current: string;
  navigate: (key: string) => void;
};

function SectionMenu({
  items,
  current,
  navigate,
}: { items: Entry[] } & Omit<Props, "pages">) {
  const panel = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [open, setOpen] = useState(false);
  const showFrame = useRef(0);
  const Icon = items[0].icon;
  const close = () => {
    clearTimeout(timer.current);
    cancelAnimationFrame(showFrame.current);
    panel.current?.hidePopover();
  };
  const show = () => {
    clearTimeout(timer.current);
    if (
      items.length < 2 ||
      document.documentElement.dataset.navigationLayout !== "top"
    )
      return;
    const menu = panel.current;
    const bounds = trigger.current?.getBoundingClientRect();
    if (!menu || !bounds) return;
    cancelAnimationFrame(showFrame.current);
    showFrame.current = requestAnimationFrame(() => {
      if (
        !menu.isConnected ||
        document.documentElement.dataset.navigationLayout !== "top"
      )
        return;
      if (!menu.matches(":popover-open")) menu.showPopover();
      menu.style.left =
        Math.max(8, Math.min(bounds.left, innerWidth - menu.offsetWidth - 8)) +
        "px";
      menu.style.top = bounds.bottom + 6 + "px";
    });
  };
  const leave = () => {
    timer.current = setTimeout(close, 180);
  };
  useEffect(() => {
    window.addEventListener("resize", close);
    window.addEventListener("netrix:preferences", close);
    return () => {
      clearTimeout(timer.current);
      cancelAnimationFrame(showFrame.current);
      window.removeEventListener("resize", close);
      window.removeEventListener("netrix:preferences", close);
    };
  }, []);
  useEffect(close, [current]);
  const active = items.some((p) => p.key === current);
  return (
    <div className="layout-menu-group" onMouseEnter={show} onMouseLeave={leave}>
      <button
        ref={trigger}
        type="button"
        className="layout-section"
        aria-current={active ? "location" : undefined}
        aria-expanded={items.length > 1 ? open : undefined}
        onFocus={show}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            show();
            requestAnimationFrame(() =>
              panel.current
                ?.querySelector<HTMLButtonElement>("button")
                ?.focus(),
            );
          }
          if (event.key === "Escape") {
            close();
            trigger.current?.focus();
          }
        }}
        onClick={() => {
          close();
          navigate(items[0].key);
        }}
      >
        <Icon size={16} aria-hidden={true} />
        <span>{items[0].group}</span>
      </button>
      {items.length > 1 && (
        <div
          ref={panel}
          popover="auto"
          className="layout-menu-panel"
          aria-label={items[0].group + " sayfaları"}
          onToggle={(event) => setOpen(event.newState === "open")}
          onMouseEnter={() => clearTimeout(timer.current)}
          onMouseLeave={leave}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) close();
          }}
        >
          {items.map((page) => (
            <button
              key={page.key}
              aria-current={page.key === current ? "page" : undefined}
              onClick={() => {
                close();
                navigate(page.key);
              }}
            >
              <span>{page.title}</span>
              <NavigationBadge value={page.badge} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function HorizontalNavigation({ pages, ...props }: Props) {
  const groups = [...new Set(pages.map((page) => page.group))];
  return (
    <nav className="layout-horizontal-nav" aria-label="Üst menü">
      {groups.map((group) => (
        <SectionMenu
          key={group}
          items={pages.filter((p) => p.group === group)}
          {...props}
        />
      ))}
    </nav>
  );
}

export function SectionNavigation({ pages, current, navigate }: Props) {
  const group = pages.find((p) => p.key === current)?.group;
  return (
    <nav className="layout-section-tabs" aria-label="Bölüm sayfaları">
      {pages
        .filter((p) => p.group === group)
        .map((p) => (
          <button
            key={p.key}
            aria-current={p.key === current ? "page" : undefined}
            onClick={() => navigate(p.key)}
          >
            <span>{p.title}</span>
            <NavigationBadge value={p.badge} />
          </button>
        ))}
    </nav>
  );
}
