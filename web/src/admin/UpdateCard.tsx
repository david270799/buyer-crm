import { CheckCircle2, Loader2, RefreshCw, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { useRequestUpdate, useUpdateStatus } from "../api/hooks";
import { errorText, useToast } from "../components/ui";
import { dateTime } from "../lib/format";

/** «Обновить CRM» (the owner, 21.10.2026): the same as
 * `git pull && docker compose up -d --build`, done by the server's updater
 * (deploy/install-updater.sh). The CRM goes off for a few minutes and comes back. */
export function UpdateCard() {
  const toast = useToast();
  const [waiting, setWaiting] = useState(false);
  const [sure, setSure] = useState(false);
  const status = useUpdateStatus(waiting);
  const request = useRequestUpdate();
  const data = status.data;
  const busy = waiting || data?.requested || data?.state === "running";
  // While the CRM restarts the server does not answer: that is part of the update.
  const restarting = waiting && status.isError;

  useEffect(() => {
    if (waiting && data && !data.requested && (data.state === "done" || data.state === "failed")) {
      setWaiting(false);
      toast(data.state === "done" ? "CRM обновлена" : "Обновление не удалось", data.state === "done" ? undefined : "error");
    }
  }, [waiting, data, toast]);

  return (
    <div className="card pad stack">
      <h3>Обновление CRM</h3>
      {!data?.installed && !status.isLoading ? (
        <div className="small muted">
          Кнопка заработает после одной команды на сервере:{" "}
          <code>cd /opt/buyer-crm &amp;&amp; git pull &amp;&amp; bash deploy/install-updater.sh</code>
        </div>
      ) : busy ? (
        <div className="row small" style={{ gap: 8 }}>
          <Loader2 className="spin" size={16} />
          {restarting
            ? "CRM перезапускается… обычно 3–10 минут, страница сама обновится."
            : "Обновляется: скачиваю новую версию и пересобираю. CRM выключится на несколько минут."}
        </div>
      ) : data?.state === "done" ? (
        <div className="row small" style={{ gap: 8 }}>
          <CheckCircle2 size={16} className="positive" />
          Обновлено {dateTime(data.finished_at)}
          {data.after ? ` · версия ${data.after}` : ""}
          {data.before && data.before === data.after ? " (новых изменений не было)" : ""}
        </div>
      ) : data?.state === "failed" ? (
        <div className="stack" style={{ gap: 6 }}>
          <div className="row small negative" style={{ gap: 8 }}>
            <TriangleAlert size={16} /> Обновление не удалось {dateTime(data.finished_at)} — CRM работает на прежней версии.
          </div>
          {data.log && <pre className="update-log">{data.log}</pre>}
        </div>
      ) : (
        <div className="small muted">То же, что команда на сервере: git pull && docker compose up -d --build.</div>
      )}
      {data?.installed && !busy && !sure && (
        <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => setSure(true)}>
          <RefreshCw size={16} /> Обновить CRM
        </button>
      )}
      {data?.installed && !busy && sure && (
        <div className="stack" style={{ gap: 8 }}>
          <div className="small">Бот и Mini App выключатся на 3–10 минут. Обновить?</div>
          <div className="row" style={{ gap: 8 }}>
            <button
              className="btn primary"
              disabled={request.isPending}
              onClick={() =>
                request.mutate(undefined, {
                  onSuccess: () => {
                    setSure(false);
                    setWaiting(true);
                  },
                  onError: (e) => toast(errorText(e), "error"),
                })
              }
            >
              {request.isPending ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />} Да, обновить
            </button>
            <button className="btn ghost" onClick={() => setSure(false)}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
