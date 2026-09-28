import { Lock, Plus } from "lucide-react";
import { useState } from "react";

import { useAddProfit, useProfit } from "../api/hooks";
import { errorText, Field, MoneyInput, Sheet, useToast } from "../components/ui";
import { date, krw } from "../lib/format";

const SHOWN = 5;

/** Admin-only block on the finance page: extra profit (cashback, rate gains...).
 * The client never sees it and the client's balance does not change. */
export function ProfitSection() {
  const profit = useProfit();
  const [adding, setAdding] = useState(false);
  const [all, setAll] = useState(false);
  const items = profit.data?.items ?? [];
  const total = items.reduce((sum, item) => sum + item.amount_krw, 0);
  const shown = all ? items : items.slice(0, SHOWN);
  return (
    <div className="section">
      <div className="card pad stack" style={{ gap: 10 }}>
        <div className="row between">
          <div>
            <h3 className="row" style={{ gap: 6 }}>
              <Lock size={14} /> Моя прибыль
            </h3>
            <div className="tiny faint">Видите только вы · баланс клиента не меняется</div>
          </div>
          <button className="btn small primary" onClick={() => setAdding(true)}>
            <Plus size={14} /> Прибыль
          </button>
        </div>
        {items.length > 0 && (
          <div className="small">
            Всего добавлено: <b className="num">{krw(total, true)}</b>
          </div>
        )}
        {profit.error ? (
          <div className="small negative">{errorText(profit.error)}</div>
        ) : items.length === 0 && !profit.isLoading ? (
          <div className="small muted">Пока нет записей. Например: кэшбэк магазина, выгода на курсе.</div>
        ) : (
          <div className="list">
            {shown.map((item) => (
              <div key={item.id} className="list-item" style={{ cursor: "default" }}>
                <div className="grow">
                  <div className="title">{item.comment || "Прибыль"}</div>
                  <div className="tiny faint num">{date(item.created_at)}</div>
                </div>
                <div className={`amount ${item.amount_krw > 0 ? "positive" : ""}`}>{krw(item.amount_krw, true)}</div>
              </div>
            ))}
          </div>
        )}
        {items.length > SHOWN && (
          <button className="btn small ghost" onClick={() => setAll(!all)}>
            {all ? "Свернуть" : `Показать все (${items.length})`}
          </button>
        )}
      </div>
      {adding && <ProfitSheet onClose={() => setAdding(false)} />}
    </div>
  );
}

function ProfitSheet({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const add = useAddProfit();
  const [amount, setAmount] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  // One key per opened form: a double tap or a retry cannot add twice.
  const [key] = useState(() => crypto.getRandomValues(new Uint32Array(3)).join("-"));
  const valid = amount !== null && amount !== 0;
  return (
    <Sheet
      title="Добавить прибыль"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn primary"
            disabled={!valid || add.isPending}
            onClick={() =>
              add.mutate(
                { amount_krw: amount!, comment: comment.trim() || null, idempotency_key: key },
                {
                  onSuccess: (r) => {
                    toast(r.already_done ? "Эта запись уже добавлена" : `Прибыль: ${krw(amount, true)}`);
                    onClose();
                  },
                  onError: (e) => toast(errorText(e), "error"),
                },
              )
            }
          >
            {add.isPending ? "Сохраняем…" : "Добавить"}
          </button>
        </>
      }
    >
      <div className="stack">
        <Field label="Сумма (минус — исправить ошибку)">
          <MoneyInput value={amount} onChange={setAmount} allowNegative autoFocus placeholder="50,000" />
        </Field>
        <Field label="Комментарий" hint="Видите только вы">
          <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Кэшбэк магазина" />
        </Field>
      </div>
    </Sheet>
  );
}
