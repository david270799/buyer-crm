// Thin wrapper over Telegram.WebApp. Everything degrades gracefully in a
// regular browser (desktop dashboard, local demo).

interface TelegramWebApp {
  initData: string;
  colorScheme: "light" | "dark";
  version: string;
  platform: string;
  ready(): void;
  expand(): void;
  isVersionAtLeast(version: string): boolean;
  setHeaderColor(color: string): void;
  setBackgroundColor(color: string): void;
  disableVerticalSwipes?(): void;
  onEvent(event: string, handler: () => void): void;
  BackButton: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void };
  HapticFeedback?: {
    notificationOccurred(type: "success" | "error" | "warning"): void;
    selectionChanged(): void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export function webApp(): TelegramWebApp | null {
  const app = window.Telegram?.WebApp;
  return app && app.initData ? app : null;
}

export function initData(): string | null {
  return webApp()?.initData || null;
}

export function colorScheme(): "light" | "dark" {
  const app = webApp();
  if (app) return app.colorScheme;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function setupTelegram(onTheme: (scheme: "light" | "dark") => void): void {
  const app = webApp();
  if (!app) return;
  app.ready();
  app.expand();
  try {
    if (app.isVersionAtLeast("7.7")) app.disableVerticalSwipes?.();
  } catch {
    /* older clients */
  }
  app.onEvent("themeChanged", () => onTheme(app.colorScheme));
}

export function syncChrome(background: string): void {
  const app = webApp();
  if (!app) return;
  try {
    app.setHeaderColor(background);
    app.setBackgroundColor(background);
  } catch {
    /* older clients */
  }
}

export function haptic(type: "success" | "error" | "warning" | "select"): void {
  const feedback = webApp()?.HapticFeedback;
  if (!feedback) return;
  if (type === "select") feedback.selectionChanged();
  else feedback.notificationOccurred(type);
}

export function backButton(visible: boolean, onClick: () => void): () => void {
  const app = webApp();
  if (!app) return () => undefined;
  if (visible) {
    app.BackButton.show();
    app.BackButton.onClick(onClick);
  } else {
    app.BackButton.hide();
  }
  return () => app.BackButton.offClick(onClick);
}
