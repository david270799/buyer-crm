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
  const upload = (picker: boolean) => {
    const form = new FormData();
    form.append("file", new File([blob], name, { type: "image/png" }));
    return api<{ prepared_id: string | null; in_chat: boolean }>(`/api/share?picker=${picker}`, {
      method: "POST",
      body: form,
    });
  };
  const picker = Boolean(app.shareMessage && app.isVersionAtLeast("8.0"));
  const result = await upload(picker);
  if (picker && result.prepared_id) {
    try {
      app.shareMessage!(result.prepared_id);
      return "picker";
    } catch {
      // Telegram refuses a second picker while it thinks the first is still
      // open («WebAppShareMessageOpened»: on Android closing the picker does
      // not always reset it, until the Mini App is reopened). Then the
      // picture goes to the chat with the bot to forward instead.
      await upload(false);
    }
  }
  return "chat";
}
