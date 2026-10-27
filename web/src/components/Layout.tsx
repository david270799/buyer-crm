import { type LucideIcon, Maximize2, Minimize2 } from "lucide-react";
import { type CSSProperties, type ReactNode, useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { backButton, canFullscreen, handleBackOverride, isFullscreen, onFullscreenChange, toggleFullscreen } from "../telegram";
import { ErrorBoundary } from "./ErrorBoundary";
import { BellButton } from "./events";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

function isActive(item: NavItem, pathname: string): boolean {
  return item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
}

/** Last query of each list page (filters like ?status=new), so coming back to
 * the list from an order keeps the filters (the owner's request, 07.10). */
const lastSearch = new Map<string, string>();

/** Telegram's native back button on nested screens (/orders/N5 → /orders). */
function useTelegramBack(nav: NavItem[]) {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    lastSearch.set(pathname, search);
  }, [pathname, search]);
  useEffect(() => {
    const parts = pathname.split("/").filter(Boolean);
    // Top-level pages that are not a tab (e.g. the client's /settings behind the gear).
    const top = ["/balance", "/notifications", "/profit"].includes(pathname) || (pathname !== "/" && !nav.some((item) => item.to === pathname));
    const nested = parts.length > 1 || top;
    const parent = parts.length > 1 ? `/${parts.slice(0, -1).join("/")}` : "/";
    return backButton(nested, () => handleBackOverride() || navigate(parent + (lastSearch.get(parent) ?? "")));
  }, [pathname, navigate, nav]);
}

const WIDE = "(min-width: 960px)";

/** True on the wide layout (sidebar), for pages that differ in more than CSS. */
export function useWide(): boolean {
  const [wide, setWide] = useState(() => window.matchMedia?.(WIDE).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(WIDE);
    if (!media) return undefined;
    const update = () => setWide(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return wide;
}

/** «Развернуть» / «Свернуть»: Telegram on a computer opens the Mini App in a
 * small window; full screen switches to the wide layout (the owner, 27.10.2026). */
export function FullscreenButton({ withLabel }: { withLabel?: boolean }) {
  const [full, setFull] = useState(isFullscreen);
  useEffect(() => onFullscreenChange(() => setFull(isFullscreen())), []);
  if (!canFullscreen()) return null;
  const label = full ? "Свернуть" : "Развернуть";
  const Icon = full ? Minimize2 : Maximize2;
  return (
    <button type="button" className={withLabel ? "side-btn" : "bell"} onClick={toggleFullscreen} aria-label={label} title={label}>
      <Icon size={withLabel ? 17 : 19} strokeWidth={1.8} />
      {withLabel && label}
    </button>
  );
}

export function Shell({
  nav,
  title,
  children,
  homes = ["/"],
  switcher,
  topActions,
}: {
  nav: NavItem[];
  title: string;
  children: ReactNode;
  /** Pages with the top bar (bell and the mode switch). */
  homes?: string[];
  switcher?: ReactNode;
  /** Extra round buttons next to the bell (the client's settings gear). */
  topActions?: ReactNode;
}) {
  const { pathname } = useLocation();
  useTelegramBack(nav);
  // Braces matter: an effect may return only a cleanup function. Telegram's
  // webview can make window.scrollTo return a value, and React would then
  // call it as a cleanup on the next navigation ("n is not a function").
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  const activeTab = nav.findIndex((item) => isActive(item, pathname));
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo">B</span>
          {title}
        </div>
        {switcher && <div className="side-switch">{switcher}</div>}
        {nav.map((item) => (
          <NavLink key={item.to} to={pathname === item.to ? item.to : item.to + (lastSearch.get(item.to) ?? "")} className={isActive(item, pathname) ? "active" : ""}>
            <item.icon size={18} strokeWidth={1.8} />
            {item.label}
          </NavLink>
        ))}
        <div className="spacer" />
        {/* The top bar is hidden on a wide screen: its buttons live here. */}
        <div className="side-foot">
          <div className="side-actions">
            {topActions}
            <BellButton />
          </div>
          <FullscreenButton withLabel />
          <div className="tiny faint">Время: Сеул (KST)</div>
        </div>
      </aside>
      <main className="main">
        {/* Only on the home page (owner, 11.10): elsewhere it took room. */}
        {homes.includes(pathname) && (
          <header className="topbar">
            {switcher ?? <span className="topbar-title">{title}</span>}
            <div className="topbar-actions">
              <FullscreenButton />
              {topActions}
              <BellButton />
            </div>
          </header>
        )}
        <ErrorBoundary resetKey={pathname}>
          <div className="page-anim" key={pathname}>
            {children}
          </div>
        </ErrorBoundary>
      </main>
      <nav
        className="tabbar"
        aria-label="Навигация"
        style={{ "--tab-count": nav.length, "--tab-index": Math.max(0, activeTab) } as CSSProperties}
      >
        {/* The highlight capsule slides between sections (iPhone-like). */}
        {activeTab >= 0 && <span className="tab-pill" aria-hidden="true" />}
        {nav.map((item) => (
          <NavLink key={item.to} to={pathname === item.to ? item.to : item.to + (lastSearch.get(item.to) ?? "")} className={isActive(item, pathname) ? "active" : ""}>
            <item.icon size={21} strokeWidth={1.8} />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function PageHead({ title, sub, action }: { title: string; sub?: ReactNode; action?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <div className="sub small muted">{sub}</div>}
      </div>
      {action}
    </div>
  );
}
