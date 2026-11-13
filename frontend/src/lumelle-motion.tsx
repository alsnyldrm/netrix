import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
} from "react";
import { flushSync } from "react-dom";

// Measured against Lumelle's live customers/people demo. Keep the independent
// title, content and navigation timelines; a page screenshot flattens them.
const powerOut = (power: number) => (t: number) => 1 - (1 - t) ** power;
const powerInOut = (power: number) => (t: number) =>
  t < 0.5 ? (2 * t) ** power / 2 : 1 - (2 * (1 - t)) ** power / 2;
const expoOut = (t: number) => (t === 1 ? 1 : 1 - 2 ** (-10 * t));
const curve = (fn: (t: number) => number) =>
  `linear(${Array.from({ length: 101 }, (_, i) => fn(i / 100).toFixed(6)).join(",")})`;
const ease = {
  out: curve(powerOut(4)),
  title: curve(powerOut(5)),
  expo: curve(expoOut),
  exit: curve((t) => t ** 3),
  fold: curve(powerInOut(5)),
};
const active = new Set<Animation>();
export const motionAllowed = () =>
  document.documentElement.dataset.reduceMotion !== "true" &&
  !matchMedia("(prefers-reduced-motion: reduce)").matches &&
  document.visibilityState === "visible";

function play(
  el: Element,
  frames: Keyframe[],
  duration: number,
  easing: string,
  delay = 0,
  id = "lumelle-reveal",
) {
  const animation = el.animate(frames, {
    duration,
    easing,
    delay,
    fill: "backwards",
  });
  animation.id = id;
  active.add(animation);
  void animation.finished.then(
    () => active.delete(animation),
    () => active.delete(animation),
  );
  return animation;
}
const cancel = (animations: Animation[]) =>
  animations.forEach((a) => a.cancel());
const visible = (el: Element) => {
  const box = el.getBoundingClientRect();
  return box.height > 0 && box.bottom > 0 && box.top < innerHeight;
};
const surfaces = (view: Element) => {
  const selector =
    ".panel, .fw-panel, .metric, .quick-card, .connection-card, .patch-panel-card, .fw-summary";
  return [...view.querySelectorAll(selector)].filter(
    (el) => visible(el) && !el.parentElement?.closest(selector),
  );
};

export function MotionTitle({ children }: { children: string }) {
  const title = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    if (!title.current || !motionAllowed()) return;
    const animations = [...title.current.querySelectorAll(".motion-char")].map(
      (el, i) =>
        play(
          el,
          [
            { transform: "translateY(115%) rotate(6deg)" },
            { transform: "none" },
          ],
          850,
          ease.title,
          i * 22,
          "lumelle-title",
        ),
    );
    return () => cancel(animations);
  }, [children]);
  return (
    <h1 ref={title} aria-label={children}>
      {children.split(/(\s+)/).map((word, i) =>
        /\s/.test(word) ? (
          <Fragment key={i}>{word}</Fragment>
        ) : (
          <span className="motion-word" aria-hidden="true" key={i}>
            {[...word].map((letter, j) => (
              <span className="motion-char" key={j}>
                {letter}
              </span>
            ))}
          </span>
        ),
      )}
    </h1>
  );
}

export function usePageMotion(page: string, account?: string) {
  const animations = useRef<Animation[]>([]);
  const generation = useRef(0);
  const direction = useRef(1);
  useEffect(() => {
    // Finish in-flight motion when either accessibility setting changes.
    const finish = () => {
      if (!motionAllowed()) [...active].forEach((a) => a.finish());
    };
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    const observer = new MutationObserver(finish);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-reduce-motion"],
    });
    media.addEventListener("change", finish);
    document.addEventListener("visibilitychange", finish);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", finish);
      document.removeEventListener("visibilitychange", finish);
    };
  }, []);
  useLayoutEffect(() => {
    if (!account || !motionAllowed()) return;
    const shell = document.querySelector(".app-shell");
    if (!shell) return;
    const next: Animation[] = [];
    const reveal = (
      selector: string,
      x: number,
      y: number,
      duration: number,
      delay: number,
      stagger = 0,
      easing = ease.out,
    ) => {
      shell.querySelectorAll(selector).forEach((el, i) =>
        next.push(
          play(
            el,
            [
              { opacity: 0, transform: `translate(${x}px, ${y}px)` },
              { opacity: 1, transform: "none" },
            ],
            duration,
            easing,
            delay + i * stagger,
            "lumelle-chrome-enter",
          ),
        ),
      );
    };
    if (innerWidth > 760) {
      reveal(".sidebar", -40, 0, 800, 0, 0, ease.expo);
      reveal(
        ".sidebar-head > *, .nav-section-label, .nav-group-title, .lumelle-sidebar-health",
        -12,
        0,
        500,
        120,
        22,
      );
    } else {
      reveal(".mobile-dock", 0, 100, 700, 200, 0, ease.expo);
    }
    reveal(".topbar", 0, -20, 700, 150, 0, ease.expo);
    reveal(".topbar > *, .lumelle-tools > *", 0, -8, 450, 250, 30);
    return () => cancel(next);
  }, [account]);
  useLayoutEffect(() => {
    const view = document.querySelector(".page-view");
    if (!view || !motionAllowed()) return;
    const next = [
      play(
        view,
        [
          { transform: `translateX(${direction.current * 26}px)` },
          { transform: "none" },
        ],
        700,
        ease.expo,
        0,
        "lumelle-page-enter",
      ),
    ];
    surfaces(view).forEach((el, i) =>
      next.push(
        play(
          el,
          [
            { opacity: 0, transform: "translateY(26px) scale(.985)" },
            { opacity: 1, transform: "none" },
          ],
          800,
          ease.expo,
          i * 60,
          "lumelle-card-enter",
        ),
      ),
    );
    // An API-backed table can arrive after the page has mounted. Reveal its
    // first visible batch once, then detach so filtering/live updates stay still.
    const rowsObserver = new MutationObserver(revealRows);
    function revealRows() {
      const rows = [
        ...view!.querySelectorAll("tbody tr:has(td:not([colspan]))"),
      ]
        .filter(visible)
        .slice(0, 16);
      if (!rows.length) return;
      rowsObserver.disconnect();
      rows.forEach((el, i) =>
        next.push(
          play(
            el,
            [
              { opacity: 0, transform: "translateY(12px)" },
              { opacity: 1, transform: "none" },
            ],
            550,
            ease.out,
            250 + i * 25,
            "lumelle-row-enter",
          ),
        ),
      );
    }
    rowsObserver.observe(view, { childList: true, subtree: true });
    revealRows();
    // Only the current page entrance; live query updates do not replay it.
    animations.current = next;
    const id = generation.current;
    void Promise.allSettled(next.map((a) => a.finished)).then(() => {
      if (generation.current === id)
        delete document.documentElement.dataset.routeMotion;
    });
    return () => {
      rowsObserver.disconnect();
      cancel(next);
    };
  }, [page, account]);
  useEffect(
    () => () => {
      generation.current++;
      cancel(animations.current);
    },
    [],
  );

  return useCallback((backward: boolean | null, update: () => void) => {
    const id = ++generation.current;
    cancel(animations.current);
    const view = document.querySelector<HTMLElement>(".page-view");
    direction.current = backward ? -1 : 1;
    const commit = () => {
      if (generation.current !== id) return;
      // Remove old effects before React reuses any nodes in the new page.
      cancel(animations.current);
      window.scrollTo({ top: 0, behavior: "instant" });
      flushSync(update);
      if (!motionAllowed()) delete document.documentElement.dataset.routeMotion;
    };
    if (!view || backward === null || !motionAllowed()) {
      commit();
      delete document.documentElement.dataset.routeMotion;
      return;
    }
    document.documentElement.dataset.routeMotion = backward
      ? "backward"
      : "forward";
    const exit = play(
      view,
      [
        { transform: "none" },
        { transform: `translateX(${-direction.current * 16}px)` },
      ],
      180,
      ease.exit,
      0,
      "lumelle-page-exit",
    );
    const next = [exit];
    surfaces(view).forEach((el, i) =>
      next.push(
        play(
          el,
          [
            { opacity: 1, transform: "none" },
            { opacity: 0, transform: "translateY(8px) scale(.985)" },
          ],
          180,
          ease.exit,
          i * 8,
          "lumelle-card-exit",
        ),
      ),
    );
    view
      .querySelectorAll(
        ".page-heading, .overview-heading, .lumelle-section-tabs",
      )
      .forEach((el) =>
        next.push(
          play(
            el,
            [
              { opacity: 1, transform: "none" },
              { opacity: 0, transform: "translateY(-6px)" },
            ],
            144,
            curve((t) => t * t),
            0,
            "lumelle-heading-exit",
          ),
        ),
      );
    next.forEach((animation) =>
      animation.effect?.updateTiming({ fill: "both" }),
    );
    animations.current = next;
    void exit.finished.then(commit, () => {});
  }, []);
}

export function useSubmenuMotion(
  group: string | null,
  collapsed: boolean,
  drawer: boolean,
) {
  useLayoutEffect(() => {
    if (!motionAllowed() || (collapsed && !drawer)) return;
    const next: Animation[] = [];
    document
      .querySelectorAll('.nav-group-items[data-open="true"]')
      .forEach((menu) => {
        next.push(
          play(
            menu,
            [
              { clipPath: "inset(0 0 100% 0)" },
              { clipPath: "inset(0 0 0% 0)" },
            ],
            450,
            ease.out,
            0,
            "lumelle-submenu",
          ),
        );
        menu.querySelectorAll(".nav-item").forEach((el, i) =>
          next.push(
            play(
              el,
              [
                { opacity: 0, transform: "translateX(-8px)" },
                { opacity: 1, transform: "none" },
              ],
              400,
              ease.out,
              80 + i * 40,
              "lumelle-menu-label",
            ),
          ),
        );
      });
    return () => cancel(next);
  }, [group, collapsed, drawer]);
}

// The leading edge arrives first; the trailing edge follows, as in Lumelle.
export function moveNavMarker(
  marker: HTMLElement,
  top: number,
  height: number,
  animate: boolean,
) {
  const current = marker.getBoundingClientRect();
  const parent = marker.parentElement!;
  const oldTop =
    current.top - parent.getBoundingClientRect().top + parent.scrollTop;
  const oldBottom = oldTop + current.height;
  const bottom = top + height;
  marker.getAnimations().forEach((a) => a.cancel());
  marker.style.height = `${height}px`;
  marker.style.transform = `translateY(${top}px)`;
  if (!animate || !motionAllowed() || current.height === 0) return;
  const down = top > oldTop;
  play(
    marker,
    Array.from({ length: 56 }, (_, i) => {
      const time = i * 10;
      const leading = powerOut(4)(Math.min(1, time / 360));
      const trailing = powerInOut(4)(Math.min(1, time / 550));
      const t = oldTop + (top - oldTop) * (down ? trailing : leading);
      const b = oldBottom + (bottom - oldBottom) * (down ? leading : trailing);
      return {
        offset: i / 55,
        transform: `translateY(${t}px)`,
        height: `${Math.max(0, b - t)}px`,
      };
    }),
    550,
    "linear",
    0,
    "lumelle-nav-marker",
  );
}

export function useSidebarMotion(
  collapsed: boolean,
  change: (next: boolean) => void,
) {
  const running = useRef<{ finish: () => void } | null>(null);
  useEffect(() => {
    const finish = () => running.current?.finish();
    window.addEventListener("resize", finish);
    return () => {
      finish();
      window.removeEventListener("resize", finish);
    };
  }, []);
  return () => {
    if (running.current) {
      running.current.finish();
      if (
        document
          .querySelector(".app-shell")
          ?.classList.contains("collapsed") === !collapsed
      )
        return;
    }
    const shell = document.querySelector<HTMLElement>(".app-shell");
    const side = shell?.querySelector<HTMLElement>(".sidebar");
    const main = shell?.querySelector<HTMLElement>(".main-shell");
    if (!shell || !side || !main || !motionAllowed() || innerWidth <= 760) {
      change(!collapsed);
      return;
    }
    const next: Animation[] = [];
    const iconSelector =
      ".nav-group-title > svg:first-child, .brand img, .sidebar-collapse, .lumelle-health-ring";
    const labels =
      ".nav-group-title > span, .nav-section-label, .nav-item, .brand-text, .lumelle-sidebar-health > span:last-child";
    const icons = [...side.querySelectorAll(iconSelector)];
    const before = icons.map((el) => el.getBoundingClientRect());
    const oldWidth = side.getBoundingClientRect().width;
    let committed = false;
    const commit = () => {
      if (committed) return;
      committed = true;
      flushSync(() => change(!collapsed));
    };
    const task = {
      finish: () => {
        commit();
        cleanup();
      },
    };
    const cleanup = () => {
      if (running.current !== task) return;
      cancel(next);
      shell.style.removeProperty("grid-template-columns");
      side.style.removeProperty("width");
      delete shell.dataset.sidebarMotion;
      running.current = null;
    };
    running.current = task;
    shell.dataset.sidebarMotion = collapsed ? "expand" : "collapse";
    const flipIcons = (delay: number) =>
      icons.forEach((el, i) => {
        const after = el.getBoundingClientRect();
        const x = before[i].x + before[i].width / 2 - after.x - after.width / 2;
        const y =
          before[i].y + before[i].height / 2 - after.y - after.height / 2;
        next.push(
          play(
            el,
            [{ transform: `translate(${x}px, ${y}px)` }, { transform: "none" }],
            550,
            ease.expo,
            delay + i * 12,
            "lumelle-sidebar-icon",
          ),
        );
      });
    const radius = getComputedStyle(side).borderTopLeftRadius;
    if (collapsed) {
      commit();
      const width = side.getBoundingClientRect().width;
      next.push(
        play(
          main,
          [
            { transform: `translateX(${oldWidth - width}px)` },
            { transform: "none" },
          ],
          620,
          ease.expo,
          0,
          "lumelle-sidebar-expand",
        ),
      );
      next.push(
        play(
          side,
          [
            { clipPath: `inset(0 ${width - oldWidth}px 0 0 round ${radius})` },
            { clipPath: `inset(0 0px 0 0 round ${radius})` },
          ],
          620,
          ease.expo,
        ),
      );
      flipIcons(20);
      side.querySelectorAll(labels).forEach((el, i) =>
        next.push(
          play(
            el,
            [
              { opacity: 0, transform: "translateX(-12px)" },
              { opacity: 1, transform: "none" },
            ],
            420,
            ease.out,
            160 + i * 12,
            "lumelle-sidebar-label",
          ),
        ),
      );
      void Promise.allSettled(next.map((a) => a.finished)).then(() => {
        if (running.current === task) cleanup();
      });
    } else {
      const width = 84;
      shell.style.gridTemplateColumns = `${width}px minmax(0, 1fr)`;
      side.style.width = `${oldWidth}px`;
      next.push(
        play(
          main,
          [
            { transform: `translateX(${oldWidth - width}px)` },
            { transform: "none" },
          ],
          600,
          ease.fold,
          60,
          "lumelle-sidebar-collapse",
        ),
      );
      side.querySelectorAll(labels).forEach((el, i) =>
        next.push(
          play(
            el,
            [
              { opacity: 1, transform: "none" },
              { opacity: 0, transform: "translateX(-10px)" },
            ],
            180,
            ease.exit,
            i * 6,
            "lumelle-sidebar-label",
          ),
        ),
      );
      next
        .filter((a) => a.id === "lumelle-sidebar-label")
        .forEach((a) => a.effect?.updateTiming({ fill: "both" }));
      const fold = play(
        side,
        [
          { clipPath: `inset(0 0px 0 0 round ${radius})` },
          { clipPath: `inset(0 ${oldWidth - width}px 0 0 round ${radius})` },
        ],
        600,
        ease.fold,
        60,
      );
      next.push(fold);
      void fold.finished.then(
        () => {
          if (running.current !== task) return;
          commit();
          side.style.removeProperty("width");
          shell.style.removeProperty("grid-template-columns");
          flipIcons(0);
          void Promise.allSettled(next.map((a) => a.finished)).then(() => {
            if (running.current === task) cleanup();
          });
        },
        () => {},
      );
    }
  };
}
