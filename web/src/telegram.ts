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
  shareMessage?(msgId: string, callback?: (sent: boolean) => void): void;
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

let backOverride: (() => void) | null = null;

/** A full-screen layer (the card preview) takes Telegram's back button until
 * it closes: «назад» closes the layer instead of leaving the page. */
export function overrideBack(onBack: () => void): () => void {
  backOverride = onBack;
  return () => {
    if (backOverride === onBack) backOverride = null;
  };
}

/** True when a layer handled «назад». */
export function handleBackOverride(): boolean {
  if (!backOverride) return false;
  backOverride();
  return true;
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

/** Save several photos (the «Витрина», the owner: «не одну, а все»). One share
 * sheet with all files where the phone offers it («Сохранить N фото» on iPhone);
 * else Telegram downloads them one after another; else plain downloads. */
export async function downloadFiles(files: { url: string; name: string }[]): Promise<void> {
  const absolute = files.map((f) => ({ url: new URL(f.url, window.location.href).toString(), name: f.name }));
  try {
    if (navigator.canShare) {
      const blobs = await Promise.all(absolute.map((f) => fetch(f.url).then((r) => r.blob())));
      const shared = blobs.map((b, i) => new File([b], absolute[i].name, { type: b.type || "image/jpeg" }));
      if (navigator.canShare({ files: shared })) {
        await navigator.share({ files: shared });
        return;
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return; // closed the sheet
  }
  const app = webApp();
  if (app?.downloadFile && app.isVersionAtLeast("8.0") && absolute.every((f) => f.url.startsWith("https://"))) {
    for (const file of absolute) {
      const accepted = await new Promise<boolean>((resolve) =>
        app.downloadFile!({ url: file.url, file_name: file.name }, (ok) => resolve(ok)),
      );
      if (!accepted) return;
    }
    return;
  }
  for (const file of absolute) {
    downloadFile(file.url, file.name);
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
}
