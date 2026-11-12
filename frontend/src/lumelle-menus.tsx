import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  Bell,
  Check,
  GearSix,
  HardDrives,
  Monitor,
  Moon,
  Plus,
  ShieldCheck,
  SignOut,
  SquaresFour,
  Sun,
  TreeStructure,
  UserCircle,
  Users,
} from "@phosphor-icons/react";
import { useLiveQuery } from "./data";
import { UserPortrait } from "./profile-avatar";
import { formatDate } from "./preferences";
import type { ThemePreference } from "./preferences";

type Menu = "notices" | "create" | "account";
type Notice = {
  id: string;
  message: string;
  created_at: string;
  state: string;
};
export const createShortcuts = [
  { key: "devices", label: "Cihaz", Icon: HardDrives },
  { key: "vlans", label: "VLAN", Icon: TreeStructure },
  { key: "sites", label: "Lokasyon", Icon: SquaresFour },
] as const;

export function LumelleMenus({
  displayName,
  role,
  avatarUrl,
  preference,
  chooseTheme,
  connected,
  alertCount,
  refresh,
  canWrite,
  canManageUsers,
  onCreate,
  onNavigate,
  onProfile,
  onShortcuts,
  onLogout,
}: {
  displayName: string;
  role: string;
  avatarUrl?: string | null;
  preference: ThemePreference;
  chooseTheme?: (mode: ThemePreference, origin?: HTMLElement) => void;
  connected: boolean;
  alertCount: number;
  refresh: number;
  canWrite: boolean;
  canManageUsers: boolean;
  onCreate: (key: string) => void;
  onNavigate: (key: string) => void;
  onProfile: () => void;
  onShortcuts: () => void;
  onLogout: () => void;
}) {
  const [menu, setMenu] = useState<Menu | null>(null);
  const menus = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const notices = useLiveQuery<{ items: Notice[] }>(
    menu === "notices" ? "/alerts?limit=5" : null,
    refresh,
  );
  const toggle = (next: Menu, button: HTMLButtonElement) => {
    trigger.current = button;
    setMenu(menu === next ? null : next);
  };
  const run = (action: () => void) => {
    trigger.current?.focus({ preventScroll: true });
    setMenu(null);
    action();
  };

  useEffect(() => {
    if (!menu) return;
    const outside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !menus.current?.contains(event.target)
      )
        setMenu(null);
    };
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenu(null);
        trigger.current?.focus({ preventScroll: true });
      } else if ((event.ctrlKey || event.metaKey) && event.key === "k") {
        setMenu(null);
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", close);
    };
  }, [menu]);

  return (
    <div className="lumelle-tools" ref={menus}>
      <div className="lumelle-menu-anchor">
        <button
          className="icon-button topbar-alerts"
          aria-label="Bildirimler"
          aria-expanded={menu === "notices"}
          aria-controls="lumelle-notices"
          onClick={(event) => toggle("notices", event.currentTarget)}
        >
          <Bell size={19} aria-hidden="true" />
          {alertCount > 0 && <span className="nav-count">{alertCount}</span>}
        </button>
        <section
          id="lumelle-notices"
          className="lumelle-popover lumelle-notices"
          data-open={menu === "notices"}
          inert={menu !== "notices"}
          aria-label="Bildirimler"
        >
          <header>
            <b>Bildirimler</b>
            <button
              className="text-button"
              onClick={() => run(() => onNavigate("alerts"))}
            >
              Alarm akışı
            </button>
          </header>
          {notices.loading ? (
            <p className="lumelle-notice-empty" role="status">
              Bildirimler yükleniyor…
            </p>
          ) : notices.error ? (
            <p className="lumelle-notice-empty" role="alert">
              {notices.error}
            </p>
          ) : notices.data?.items.length ? (
            notices.data.items.map((notice) => (
              <button
                className="lumelle-notice"
                key={notice.id}
                onClick={() => run(() => onNavigate("alerts"))}
              >
                <span className="lumelle-notice-icon">
                  <Bell size={17} aria-hidden="true" />
                </span>
                <span>
                  <b>{notice.message}</b>
                  <small>
                    <time dateTime={notice.created_at}>
                      {formatDate(notice.created_at)}
                    </time>
                  </small>
                </span>
                {notice.state === "firing" && <i aria-label="Aktif alarm" />}
              </button>
            ))
          ) : (
            <p className="lumelle-notice-empty">Bildirim yok.</p>
          )}
        </section>
      </div>
      {canWrite && (
        <div className="lumelle-menu-anchor">
          <button
            className="primary topbar-create"
            aria-label="Yeni"
            aria-expanded={menu === "create"}
            aria-controls="lumelle-create"
            onClick={(event) => toggle("create", event.currentTarget)}
          >
            <Plus size={18} aria-hidden="true" /> <span>Yeni</span>
          </button>
          <section
            id="lumelle-create"
            className="lumelle-popover lumelle-create-menu"
            data-open={menu === "create"}
            inert={menu !== "create"}
            aria-label="Yeni kayıt"
          >
            <h2>Oluştur</h2>
            {createShortcuts.map(({ key, label, Icon }) => (
              <button key={key} onClick={() => run(() => onCreate(key))}>
                <Icon size={17} aria-hidden="true" /> {label}
              </button>
            ))}
            <hr />
            <button onClick={() => run(() => onNavigate("discovery"))}>
              <ShieldCheck size={17} aria-hidden="true" /> Ağ keşfi
            </button>
          </section>
        </div>
      )}
      <div className="lumelle-menu-anchor">
        <button
          className="topbar-profile"
          aria-label="Hesap menüsü"
          aria-expanded={menu === "account"}
          aria-controls="lumelle-account"
          onClick={(event) => toggle("account", event.currentTarget)}
        >
          <UserPortrait name={displayName} url={avatarUrl} />
          {connected && (
            <i className="lumelle-avatar-status" aria-hidden="true" />
          )}
        </button>
        <section
          id="lumelle-account"
          className="lumelle-popover lumelle-account-menu"
          data-open={menu === "account"}
          inert={menu !== "account"}
          aria-label="Hesap menüsü"
        >
          <h2>
            {displayName} · {role}
          </h2>
          {chooseTheme && (
            <>
              {(
                [
                  ["light", "Açık", Sun],
                  ["dark", "Koyu", Moon],
                  ["system", "Sistemle eşleş", Monitor],
                ] as const
              ).map(([mode, label, Icon]) => (
                <button
                  key={mode}
                  aria-pressed={preference === mode}
                  onClick={() =>
                    run(() => chooseTheme(mode, trigger.current ?? undefined))
                  }
                >
                  <Icon size={17} aria-hidden="true" /> {label}
                  {preference === mode && (
                    <Check size={14} aria-hidden="true" />
                  )}
                </button>
              ))}
              <hr />
            </>
          )}
          <button onClick={() => run(onProfile)}>
            <UserCircle size={17} aria-hidden="true" /> Profil
          </button>
          <button onClick={() => run(() => onNavigate("settings"))}>
            <GearSix size={17} aria-hidden="true" /> Sistem ayarları
          </button>
          {canManageUsers && (
            <button onClick={() => run(() => onNavigate("users"))}>
              <Users size={17} aria-hidden="true" /> Kullanıcılar
            </button>
          )}
          <button onClick={() => run(onShortcuts)}>
            <SquaresFour size={17} aria-hidden="true" /> Klavye kısayolları{" "}
            <kbd>?</kbd>
          </button>
          <hr />
          <button className="lumelle-signout" onClick={() => run(onLogout)}>
            <SignOut size={17} aria-hidden="true" /> Güvenli çıkış
          </button>
        </section>
      </div>
    </div>
  );
}

export function LumelleSectionTabs({
  label,
  pages,
  current,
  previous,
  onNavigate,
}: {
  label: string;
  pages: { key: string; title: string }[];
  current: string;
  previous: string;
  onNavigate: (key: string) => void;
}) {
  const tabs = useRef<HTMLElement>(null);
  const indicator = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const nav = tabs.current;
    const marker = indicator.current;
    const active = nav?.querySelector<HTMLButtonElement>(
      '[aria-current="page"]',
    );
    if (!nav || !marker || !active) return;
    const align = () => {
      marker.style.left = `${active.offsetLeft}px`;
      marker.style.width = `${active.offsetWidth}px`;
    };
    align();
    const before = Array.from(
      nav.querySelectorAll<HTMLButtonElement>("button"),
    ).find((button) => button.dataset.route === previous);
    const reduceMotion =
      document.documentElement.dataset.reduceMotion === "true" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const motion =
      before && before !== active && !reduceMotion
        ? marker.animate(
            [
              {
                left: `${before.offsetLeft}px`,
                width: `${before.offsetWidth}px`,
              },
              {
                left: `${active.offsetLeft}px`,
                width: `${active.offsetWidth}px`,
              },
            ],
            { duration: 320, easing: "cubic-bezier(0.2, 0.65, 0.2, 1)" },
          )
        : undefined;
    if (active.offsetLeft + active.offsetWidth > nav.clientWidth)
      nav.scrollLeft = active.offsetLeft + active.offsetWidth - nav.clientWidth;
    const resize = new ResizeObserver(align);
    resize.observe(nav);
    nav.querySelectorAll("button").forEach((button) => resize.observe(button));
    return () => {
      motion?.cancel();
      resize.disconnect();
    };
  }, [current, previous]);

  return (
    <nav
      className="lumelle-section-tabs"
      aria-label={`${label} sayfaları`}
      ref={tabs}
    >
      <span className="lumelle-tab-marker" ref={indicator} aria-hidden="true" />
      {pages.map((page) => (
        <button
          key={page.key}
          data-route={page.key}
          aria-current={page.key === current ? "page" : undefined}
          onClick={() => onNavigate(page.key)}
        >
          {page.title}
        </button>
      ))}
    </nav>
  );
}
