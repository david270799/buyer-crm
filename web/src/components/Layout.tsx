import type { LucideIcon } from "lucide-react";
import { type CSSProperties, type ReactNode, useEffect } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { backButton } from "../telegram";
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
function useTelegramBack() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    lastSearch.set(pathname, search);
  }, [pathname, search]);
  useEffect(() => {
    const parts = pathname.split("/").filter(Boolean);
    const top = ["/balance", "/notifications", "/profit"].includes(pathname);
    const nested = parts.length > 1 || top;
    const parent = parts.length > 1 ? `/${parts.slice(0, -1).join("/")}` : "/";
    return backButton(nested, () => navigate(parent + (lastSearch.get(parent) ?? "")));
  }, [pathname, navigate]);
}

export function Shell({ nav, title, children }: { nav: NavItem[]; title: string; children: ReactNode }) {
  const { pathname } = useLocation();
  useTelegramBack();
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
        {nav.map((item) => (
          <NavLink key={item.to} to={pathname === item.to ? item.to : item.to + (lastSearch.get(item.to) ?? "")} className={isActive(item, pathname) ? "active" : ""}>
            <item.icon size={18} strokeWidth={1.8} />
            {item.label}
          </NavLink>
        ))}
        <div className="spacer" />
        <div className="tiny faint" style={{ padding: "0 12px" }}>
          Время: Сеул (KST)
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <span className="topbar-title">{title}</span>
          <BellButton />
        </header>
        <ErrorBoundary resetKey={pathname}>{children}</ErrorBoundary>
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
