import { Send } from "lucide-react";
import { useState } from "react";

import { sharePicture } from "../lib/share";
import { errorText, useToast } from "./ui";

/** «Поделиться»: builds the picture and hands it to Telegram to send by hand. */
export function ShareButton({
  make,
  name,
  className = "btn small icon-only",
  size = 16,
}: {
  make: () => Promise<Blob>;
  name: string;
  className?: string;
  size?: number;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const share = async () => {
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
  return (
    <button type="button" className={className} onClick={share} disabled={busy} aria-label="Поделиться" title="Поделиться">
      <Send size={size} />
    </button>
  );
}
