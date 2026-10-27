import { AlertTriangle, CheckCircle2, ChevronRight, Hourglass, type LucideIcon, PackageCheck, Plane, ShoppingCart } from "lucide-react";
import { Link } from "react-router-dom";

import type { Overview } from "../api/types";
import { Thumb } from "../components/orders";
import { StatusBadge } from "../components/status";
import { krw, orderTitle, plural, shortDate, sizeText, usd } from "../lib/format";

interface Task {
  icon: LucideIcon;
  title: string;
  hint: string;
  to: string;
  action: string;
  warning?: boolean;
  primary?: boolean;
}

function tasks(o: Overview["orders"]): Task[] {
  const n = o.status_counts;
  const list: Task[] = [];
  if (o.attention_count)
    list.push({
      icon: AlertTriangle,
      title: `${o.attention_count} ${plural(o.attention_count, "заказ требует", "заказа требуют", "заказов требуют")} внимания`,
      hint: "Вопрос по размеру, фото или от клиента",
      to: "/orders?attention=1",
      action: "Открыть",
      warning: true,
    });
  if (o.stuck_count)
    list.push({
      icon: Hourglass,
      title: `${o.stuck_count} ${plural(o.stuck_count, "заказ не пришёл", "заказа не пришли", "заказов не пришли")} на склад`,
      hint: "Выкуплены 4+ дня назад",
      to: "/orders?stuck=1",
      action: "Показать",
      warning: true,
    });
  if (n.new)
    list.push({
      icon: ShoppingCart,
      title: `${n.new} ${plural(n.new, "новый заказ", "новых заказа", "новых заказов")} — выкупить`,
      hint: "Статус «Новый заказ»",
      to: "/orders?status=new",
      action: "Выкупить",
      primary: true,
    });
  if (n.warehouse)
    list.push({
      icon: PackageCheck,
      title: `${n.warehouse} ${plural(n.warehouse, "заказ", "заказа", "заказов")} на складе — можно отправлять`,
      hint: "Статус «На складе»",
      to: "/orders?status=warehouse",
      action: "Отправить",
    });
  if (n.cargo)
    list.push({
      icon: Plane,
      title: `${n.cargo} ${plural(n.cargo, "заказ", "заказа", "заказов")} в пути`,
      hint: "Отметьте посылку, когда придёт",
      to: "/shipments",
      action: "Открыть",
    });
  return list;
}

/** Wide screen «Сводка» (variant 1, the owner, 27.10.2026): a strip with the
 * balance and profit, «Что сделать сейчас» and the latest orders. */
export function DeskDashboard({ data }: { data: Overview }) {
  const o = data.orders;
  const b = data.balance;
  const n = o.status_counts;
  const todo = tasks(o);
  const work = [
    n.new && `${n.new} ${plural(n.new, "новый", "новых", "новых")}`,
    n.bought && `${n.bought} ${plural(n.bought, "выкуплен", "выкуплено", "выкуплено")}`,
    n.warehouse && `${n.warehouse} на складе`,
    n.cargo && `${n.cargo} в пути`,
  ].filter(Boolean);
  return (
    <>
      <div className="balance-strip dash-strip">
        <Link to="/finance" className={`big ${b.krw < 0 ? "debt" : ""}`}>
          <div className="cap">
            Баланс клиента{b.krw < 0 && <span className="debt-badge">долг</span>}
          </div>
          <div className="k num">{krw(b.krw)}</div>
          <div className="tiny num">
            {b.usd !== null ? usd(b.usd) : "курс $ не задан"}
            {b.krw_per_usd ? ` · 1 $ = ${b.krw_per_usd.toLocaleString("en-US")} ₩` : ""}
          </div>
        </Link>
        <Link to="/profit?period=month">
          <div className="cap">Прибыль · месяц</div>
          <div className="s num positive">{krw(o.profit_month_krw ?? 0)}</div>
          <div className="tiny muted">подробнее →</div>
        </Link>
        <Link to="/profit?period=all">
          <div className="cap">Прибыль всего</div>
          <div className="s num positive">{krw(o.profit_total_krw ?? 0)}</div>
          <div className="tiny muted">подробнее →</div>
        </Link>
        <Link to="/orders">
          <div className="cap">В работе</div>
          <div className="s num">
            {o.active} {plural(o.active, "заказ", "заказа", "заказов")}
          </div>
          <div className="tiny muted">{work.join(" · ") || "всё доставлено"}</div>
        </Link>
      </div>
      <div className="dash-cols">
        <div>
          <h2 className="dash-title">Что сделать сейчас</h2>
          <div className="card list">
            {todo.length ? (
              todo.map((task) => (
                <Link key={task.to + task.title} to={task.to} className="list-item task-row">
                  <span className={`task-icon ${task.warning ? "warning" : ""}`}>
                    <task.icon size={18} strokeWidth={1.8} />
                  </span>
                  <div className="grow">
                    <div className="title">{task.title}</div>
                    <div className="tiny muted">{task.hint}</div>
                  </div>
                  <span className={`btn small ${task.primary ? "primary" : ""}`}>{task.action}</span>
                </Link>
              ))
            ) : (
              <div className="list-item task-row" style={{ cursor: "default" }}>
                <span className="task-icon">
                  <CheckCircle2 size={18} strokeWidth={1.8} />
                </span>
                <div className="grow">
                  <div className="title">Всё сделано</div>
                  <div className="tiny muted">Новых дел нет</div>
                </div>
              </div>
            )}
          </div>
        </div>
        <div>
          <h2 className="dash-title">
            Последние заказы
            <Link to="/orders" className="link">
              Все {o.total} <ChevronRight size={14} style={{ verticalAlign: -2 }} />
            </Link>
          </h2>
          <div className="card list">
            {data.recent.slice(0, 8).map((order) => (
              <Link key={order.id} to={`/orders/${order.id}`} className="list-item">
                <Thumb src={order.thumbnail_url ?? order.photo_url} alt={orderTitle(order)} />
                <div className="grow">
                  <div className="title">
                    {order.id} · {orderTitle(order)}
                  </div>
                  <div className="tiny muted">
                    {[sizeText(order), shortDate(order.timestamps.created_at)].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <span className="amount small">{order.client_price ? krw(order.client_price) : "—"}</span>
                <StatusBadge status={order.status} />
              </Link>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
