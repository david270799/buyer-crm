import { Loader2, Send } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";

import { sharePicture } from "../lib/share";
import { errorText, useToast } from "./ui";

/** «Поделиться»: builds the picture and hands it to Telegram to send by hand. */
export function useShare(make: () => Promise<Blob>, name: string) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const share = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await sharePicture(await make(), name);
      if (result === "chat") toast("Картинка в чате с ботом — перешлите её клиенту");
      if (result === "download") toast("Картинка сохранена");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  };
  return { share, busy };
}

/** Shown while the picture is drawn and handed to Telegram (takes a few
 * seconds on a phone with many photos; the owner, 23.10.2026). */
export function ShareLoading({ busy }: { busy: boolean }) {
  if (!busy) return null;
  return createPortal(
    <div className="share-loading" role="status" aria-live="polite">
      <div className="share-loading-box">
        <Loader2 className="spin" size={28} />
        <div>Готовлю картинку…</div>
      </div>
    </div>,
    document.body,
  );
}

export function ShareButton({ make, name }: { make: () => Promise<Blob>; name: string }) {
  const { share, busy } = useShare(make, name);
  return (
    <>
      <button type="button" className="btn small icon-only" onClick={share} disabled={busy} aria-label="Поделиться" title="Поделиться">
        <Send size={16} />
      </button>
      <ShareLoading busy={busy} />
    </>
  );
}
