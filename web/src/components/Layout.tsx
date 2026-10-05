import type { LucideIcon } from "lucide-react";
import { type ReactNode, useEffect } from "react";
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

/** Telegram's native back button on nested screens (/orders/N5 → /orders). */
function useTelegramBack() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const parts = pathname.split("/").filter(Boolean);
    const nested = parts.length > 1 || pathname === "/balance" || pathname === "/notifications";
    const parent = parts.length > 1 ? `/${parts.slice(0, -1).join("/")}` : "/";
    return backButton(nested, () => navigate(parent));
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
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo">B</span>
          {title}
        </div>
        {nav.map((item) => (
          <NavLink key={item.to} to={item.to} className={isActive(item, pathname) ? "active" : ""}>
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
      <nav className="tabbar" aria-label="Навигация">
        {nav.map((item) => (
          <NavLink key={item.to} to={item.to} className={isActive(item, pathname) ? "active" : ""}>
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
