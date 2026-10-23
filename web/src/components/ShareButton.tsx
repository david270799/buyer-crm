import { Send } from "lucide-react";
import { useState } from "react";

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

export function ShareButton({ make, name }: { make: () => Promise<Blob>; name: string }) {
  const { share, busy } = useShare(make, name);
  return (
    <button type="button" className="btn small icon-only" onClick={share} disabled={busy} aria-label="Поделиться" title="Поделиться">
      <Send size={16} />
    </button>
  );
}
