import type { ReactNode } from "react";

import { useOverview, useTransactions } from "../api/hooks";
import { BalanceCard, BalanceStrip, History, HistoryTable } from "../components/money";
import { ErrorState, Loading } from "../components/ui";

export function BalancePage({
  actions,
  toolbar,
  extra,
}: {
  /** Buttons inside the balance card (phone). */
  actions?: ReactNode;
  /** The same actions as text buttons above the history (wide screen). */
  toolbar?: ReactNode;
  /** Shown between the balance card and the history (admin: own profit). */
  extra?: ReactNode;
}) {
  const overview = useOverview();
  const history = useTransactions();
  const historyState = history.isLoading ? (
    <Loading rows={5} height={64} />
  ) : history.error || !history.data ? (
    <ErrorState error={history.error} onRetry={history.refetch} />
  ) : null;
  return (
    <>
      <div className="only-mobile">
        {overview.data ? <BalanceCard balance={overview.data.balance} actions={actions} /> : overview.isLoading ? <Loading rows={1} height={110} /> : null}
        {extra}
        <div className="section">{historyState ?? <History items={history.data!.items} />}</div>
      </div>
      {/* Wide screen (variant 1, the owner, 27.10.2026): a strip with the month
          totals, then a statement-like table. */}
      <div className="only-desktop">
        {overview.data ? <BalanceStrip balance={overview.data.balance} items={history.data?.items ?? []} /> : <Loading rows={1} height={120} />}
        {extra}
        <div className="ledger-bar">
          <div className="cap">История операций</div>
          {toolbar && <div className="row" style={{ gap: 8 }}>{toolbar}</div>}
        </div>
        {historyState ?? <HistoryTable items={history.data!.items} />}
      </div>
    </>
  );
}
