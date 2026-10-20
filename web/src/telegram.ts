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
  downloadFile?(params: { url: string; file_name: string }, callback?: (accepted: boolean) => void): void;
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

/** Save a file to the phone: Telegram's own download (Bot API 8.0+, it asks
 * where to save and puts photos in the gallery), else a normal browser download. */
export function downloadFile(url: string, fileName: string): void {
  const absolute = new URL(url, window.location.href).toString();
  const app = webApp();
  if (app?.downloadFile && app.isVersionAtLeast("8.0") && absolute.startsWith("https://")) {
    app.downloadFile({ url: absolute, file_name: fileName });
    return;
  }
  const link = document.createElement("a");
  link.href = absolute;
  link.download = fileName;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}
