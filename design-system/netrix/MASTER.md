# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** NETRIX
**Generated:** 2026-10-29 17:25:45
**Category:** Smart Home/IoT Dashboard
**Design Dials:** Density 8/10 (Dense / Dashboard)

---

## Global Rules

### Color Palette

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Primary | `#1E293B` | `--color-primary` |
| On Primary | `#FFFFFF` | `--color-on-primary` |
| Secondary | `#334155` | `--color-secondary` |
| On Secondary | `#FFFFFF` | `--color-on-secondary` |
| Accent/CTA | `#22C55E` | `--color-accent` |
| On Accent/CTA | `#0F172A` | `--color-on-accent` |
| Background | `#0F172A` | `--color-background` |
| Foreground | `#F8FAFC` | `--color-foreground` |
| Card | `#1B2336` | `--color-card` |
| Card Foreground | `#F8FAFC` | `--color-card-foreground` |
| Muted | `#272F42` | `--color-muted` |
| Muted Foreground | `#94A3B8` | `--color-muted-foreground` |
| Border | `#475569` | `--color-border` |
| Destructive | `#EF4444` | `--color-destructive` |
| On Destructive | `#000000` | `--color-on-destructive` |
| Ring | `#FFFFFF` | `--color-ring` |

**Color Notes:** Dark tech + status green

### Typography

- **Heading Font:** Fira Code
- **Body Font:** Fira Sans
- **Mood:** dashboard, data, analytics, code, technical, precise
- **Google Fonts:** [Fira Code + Fira Sans](https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap)

**CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
```

### Spacing Variables

*Density: 8/10 — Dense / Dashboard*

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `2px` / `0.125rem` | Tight gaps |
| `--space-sm` | `4px` / `0.25rem` | Icon gaps, inline spacing |
| `--space-md` | `8px` / `0.5rem` | Standard padding |
| `--space-lg` | `12px` / `0.75rem` | Section padding |
| `--space-xl` | `16px` / `1rem` | Large gaps |
| `--space-2xl` | `24px` / `1.5rem` | Section margins |
| `--space-3xl` | `32px` / `2rem` | Hero padding |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Hero images, featured cards |

---

## Component Specs

### Buttons

```css
/* Primary Button */
.btn-primary {
  background: #22C55E;
  color: white;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

.btn-primary:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: #1E293B;
  border: 2px solid #1E293B;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}
```

### Cards

```css
.card {
  background: #0F172A;
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow-md);
  transition: all 200ms ease;
  cursor: pointer;
}

.card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}
```

### Inputs

```css
.input {
  padding: 12px 16px;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  font-size: 16px;
  transition: border-color 200ms ease;
}

.input:focus {
  border-color: #1E293B;
  outline: none;
  box-shadow: 0 0 0 3px #1E293B20;
}
```

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

.modal {
  background: white;
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
}
```

---

## Style Guidelines

**Style:** Glassmorphism

**Keywords:** Frosted glass, transparent, blurred background, layered, vibrant background, light source, depth, multi-layer

**Best For:** Modern SaaS, financial dashboards, high-end corporate, lifestyle apps, modal overlays, navigation

**Key Effects:** Backdrop blur (10-20px), subtle border (1px solid rgba white 0.2), light reflection, Z-depth

### Page Pattern

**Pattern Name:** Real-Time / Operations Landing

- **Conversion Strategy:** Offer a demo or sandbox and show trust signals. Label telemetry as live only when backed by a current source, with update time and stale state. Provide pause/hide or update-frequency controls for tickers and previews, stop offscreen/hidden work, support keyboard controls, and render a static final snapshot under reduced motion.
- **CTA Placement:** Primary CTA in nav + After metrics
- **Section Order:** Hero (product + live preview or status) > Key metrics/indicators > How it works > CTA (Start trial / Contact)

---

## Anti-Patterns (Do NOT Use)

- ❌ Slow updates
- ❌ No automation

### Additional Forbidden Patterns

- ❌ **Emojis as icons** — Use SVG icons (Heroicons, Lucide, Simple Icons)
- ❌ **Missing cursor:pointer** — All clickable elements must have cursor:pointer
- ❌ **Layout-shifting hovers** — Avoid scale transforms that shift layout
- ❌ **Low contrast text** — Maintain 4.5:1 minimum contrast ratio
- ❌ **Instant state changes** — Always use transitions (150-300ms)
- ❌ **Invisible focus states** — Focus states must be visible for a11y

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from consistent icon set (Heroicons/Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Light mode: text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile

## NETRIX uygulama kararları

> Bu bölüm yukarıdaki üretilmiş önerilerin önüne geçer. 29 Ekim 2026'da proje sahibi arayüzün UI UX Pro Max ile baştan yenilenmesini istedi ve aşağıdaki üç kararı seçti.

Bu bir pazarlama sayfası değildir: hero/CTA önerileri yerine operasyon panoraması, veri tabloları ve çalışma alanı navigasyonu uygulanır.

### Seçilen yön

- **Stil:** Teknik kobalt. Sakin, yoğun veri ekranlarına uygun; tek kobalt vurgu, durumlar yeşil/amber/kırmızı ve her zaman metin etiketiyle.
- **Font:** IBM Plex Sans (arayüz) + IBM Plex Mono (IP, MAC, sayaç, kod). `@fontsource` ile self-hosted; CDN veya harici font isteği yoktur.
- **Navigasyon:** Gruplu tek sidebar. Altı modül başlığı altında bütün sayfalar; masaüstünde ikon moduna daraltılabilir (tercih `localStorage` anahtarı `netrix-sidebar`), 1024 px altında kaydırmalı çekmece + karartma katmanı. Ctrl/⌘ K komut paleti korunur.

### Renk token'ları (`frontend/src/style.css`)

| Token | Açık | Koyu |
| --- | --- | --- |
| `--bg` | `#f8fafc` | `#0b1220` |
| `--surface` | `#ffffff` | `#111a2c` |
| `--surface-2` | `#f1f5f9` | `#172238` |
| `--border` | `#e2e8f0` | `#22304a` |
| `--text` | `#0f172a` | `#e2e8f0` |
| `--text-2` | `#475569` | `#b3bfd1` |
| `--text-3` | `#556275` | `#93a3ba` |
| `--accent` | `#1d4ed8` | `#60a5fa` |
| `--success` | `#15803d` | `#4ade80` |
| `--warning` | `#92400e` | `#facc15` |
| `--danger` | `#b91c1c` | `#f87171` |

Bütün metin token'ları `--bg`, `--surface` ve `--surface-2` üzerinde en az 4.5:1 kontrast verir. Bileşenler sabit renk kullanmaz; SVG topoloji ve trafik grafikleri de sınıflar üzerinden token'ları kullanır.

### Tema

- `html[data-theme]` `light` veya `dark` olur. `public/theme-init.js` ilk boyamadan önce kayıtlı tercihi (`netrix-theme`) ya da `prefers-color-scheme` değerini uygular; CSP `script-src 'self'` olduğu için satır içi betik kullanılmaz.
- Tema anahtarı giriş ekranında ve üst barda bulunur.

### Hareket

- Sayfa değişiminde içerik 240 ms içinde hafifçe yukarı kayarak belirir (`.page-view`, sayfa anahtarıyla yeniden bağlanır). Diyaloglar 200 ms ölçek + saydamlıkla açılır; çekmece 240 ms kayar.
- `prefers-reduced-motion: reduce` altında bütün animasyon ve geçişler fiilen kapanır.

### Bileşen kuralları

- Radius: 6 px (kontrol), 10 px (not/kart içi), 14 px (panel). Gölgeler yalnızca hafif ayrım için.
- Kontroller en az 40 px yükseklikte; satır işlemleri 34 px. Odak halkası `--focus` ile her zaman görünür.
- Yükleme, boş, hata ve kısmi sonuç durumları ayrı görünür. Başlangıç şeması “başlangıç şeması” olarak etiketlenir; örnek cihaz veya trafik canlı veri gibi sunulmaz.
- Native HTML dialog, Escape ile kapanma, odak iadesi, etiketli kontroller, skip link korunur. Tablolar kendi kaydırma alanında taşabilir; sayfa yatay taşmaz.
- Marka: bağlantı uçlarıyla oluşturulan N monogramı, kobalt zemin. SVG favicon ve aynı vektörden üretilen `app-icon.png` kullanılır.
