import { api } from "../api/client";
import { webApp } from "../telegram";

export type ShareResult = "picker" | "chat" | "download";

/** Send a picture on by hand («Поделиться», the owner, 23.10.2026). In Telegram
 * the server prepares it and Telegram's chat picker opens; an old Telegram gets
 * the picture in the chat with the bot to forward; a plain browser downloads it. */
export async function sharePicture(blob: Blob, name: string): Promise<ShareResult> {
  const app = webApp();
  if (!app) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
    return "download";
  }
  const picker = Boolean(app.shareMessage && app.isVersionAtLeast("8.0"));
  const form = new FormData();
  form.append("file", new File([blob], name, { type: "image/png" }));
  const result = await api<{ prepared_id: string | null; in_chat: boolean }>(`/api/share?picker=${picker}`, {
    method: "POST",
    body: form,
  });
  if (picker && result.prepared_id) {
    app.shareMessage!(result.prepared_id);
    return "picker";
  }
  return "chat";
}
