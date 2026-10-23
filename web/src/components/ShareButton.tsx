import { Download, Loader2, Send } from "lucide-react";
import { type ReactNode, useState } from "react";
import { createPortal } from "react-dom";

import { downloadPicture, sharePicture } from "../lib/share";
import { errorText, Sheet, useToast } from "./ui";

/** «Поделиться»: first asks «Отправить в чат» or «Скачать» (the owner,
 * 23.10.2026), then builds the picture and hands it to Telegram or saves it.
 * `start()` opens the question; render `ui` next to the button. */
export function useShare(make: () => Promise<Blob>, name: string): { start: () => void; busy: boolean; ui: ReactNode } {
  const toast = useToast();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const run = async (how: "send" | "download") => {
    setAsking(false);
    setBusy(true);
    try {
      const blob = await make();
      if (how === "download") {
        await downloadPicture(blob, name);
      } else {
        const result = await sharePicture(blob, name);
        if (result === "chat") toast("Картинка в чате с ботом — перешлите её клиенту");
        if (result === "download") toast("Картинка сохранена");
      }
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  };
  const ui = (
    <>
      {/* In a portal: the balance card's buttons sit in a transformed box,
          which would trap a fixed sheet inside the card. */}
      {asking &&
        createPortal(
        <Sheet title="Картинка" onClose={() => setAsking(false)}>
          <div className="stack" style={{ gap: 10 }}>
            <button className="btn primary block" onClick={() => run("send")}>
              <Send size={18} /> Отправить в чат
            </button>
            <button className="btn block" onClick={() => run("download")}>
              <Download size={18} /> Скачать
            </button>
          </div>
        </Sheet>,
          document.body,
        )}
      <ShareLoading busy={busy} />
    </>
  );
  return { start: () => !busy && setAsking(true), busy, ui };
}

/** Shown while the picture is drawn and handed on (takes a few seconds on a
 * phone with many photos; the owner, 23.10.2026). */
function ShareLoading({ busy }: { busy: boolean }) {
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
  const { start, busy, ui } = useShare(make, name);
  return (
    <>
      <button type="button" className="btn small icon-only" onClick={start} disabled={busy} aria-label="Поделиться" title="Поделиться">
        <Send size={16} />
      </button>
      {ui}
    </>
  );
}
