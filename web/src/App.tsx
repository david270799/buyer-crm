import { LogIn, ShieldAlert, UserRound } from "lucide-react";
import { useEffect, useState } from "react";

import { AdminApp } from "./admin/AdminApp";
import { ApiError, hasCredentials, setDemoRole } from "./api/client";
import { useConfig, useMe } from "./api/hooks";
import { ClientApp } from "./client/ClientApp";
import { colorScheme, setupTelegram, syncChrome } from "./telegram";

function useTheme() {
  const [scheme, setScheme] = useState(colorScheme());
  useEffect(() => {
    setupTelegram(setScheme);
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onChange = () => setScheme(colorScheme());
    media?.addEventListener?.("change", onChange);
    return () => media?.removeEventListener?.("change", onChange);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = scheme;
    syncChrome(scheme === "dark" ? "#111214" : "#f4f3ef");
  }, [scheme]);
}

function Splash() {
  return (
    <div className="center-screen">
      <div className="skeleton" style={{ width: 56, height: 56, borderRadius: 16 }} />
    </div>
  );
}

function Notice({ icon, title, text, action }: { icon: JSX.Element; title: string; text: string; action?: JSX.Element }) {
  return (
    <div className="center-screen">
      <div className="card login-card stack" style={{ alignItems: "center" }}>
        <div className="state" style={{ padding: 0 }}>
          <div className="icon">{icon}</div>
        </div>
        <h2>{title}</h2>
        <div className="muted small">{text}</div>
        {action}
      </div>
    </div>
  );
}

function DemoLogin({ onPick }: { onPick: (role: "admin" | "client") => void }) {
  return (
    <div className="center-screen">
      <div className="card login-card stack">
        <h1>Buyer CRM</h1>
        <div className="muted small">
          Демо-режим: данные в памяти сервера, Firebase не используется. Выберите, чей интерфейс открыть.
        </div>
        <button className="btn primary block" onClick={() => onPick("admin")}>
          <LogIn size={16} /> Администратор
        </button>
        <button className="btn block" onClick={() => onPick("client")}>
          <UserRound size={16} /> Клиент
        </button>
      </div>
    </div>
  );
}

export function App() {
  useTheme();
  const [credentials, setCredentials] = useState(hasCredentials());
  const config = useConfig();
  const me = useMe(credentials);

  const pickDemo = (role: "admin" | "client") => {
    setDemoRole(role);
    setCredentials(true);
  };
  const leaveDemo = () => {
    setDemoRole(null);
    window.location.reload();
  };

  if (!credentials) {
    if (config.isLoading) return <Splash />;
    if (config.data?.demo) return <DemoLogin onPick={pickDemo} />;
    return (
      <Notice
        icon={<ShieldAlert size={22} />}
        title="Откройте CRM из Telegram"
        text="Вход выполняется через Telegram: откройте бота и нажмите кнопку «CRM»."
      />
    );
  }
  if (me.isLoading) return <Splash />;
  if (me.error || !me.data) {
    const status = me.error instanceof ApiError ? me.error.status : 0;
    return (
      <Notice
        icon={<ShieldAlert size={22} />}
        title={status === 403 ? "Нет доступа" : "Не удалось войти"}
        text={me.error instanceof Error ? me.error.message : "Попробуйте открыть Mini App заново."}
        action={
          config.data?.demo ? (
            <button className="btn small" onClick={leaveDemo}>
              Выбрать другую роль
            </button>
          ) : undefined
        }
      />
    );
  }
  return me.data.role === "admin" ? <AdminApp onLeaveDemo={config.data?.demo ? leaveDemo : undefined} /> : <ClientApp />;
}
