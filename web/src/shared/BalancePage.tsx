import type { ReactNode } from "react";

import { useOverview, useTransactions } from "../api/hooks";
import { BalanceCard, History } from "../components/money";
import { ErrorState, Loading } from "../components/ui";

export function BalancePage({
  actions,
  extra,
}: {
  /** Buttons inside the balance card. */
  actions?: ReactNode;
  /** Shown between the balance card and the history (admin: own profit). */
  extra?: ReactNode;
}) {
  const overview = useOverview();
  const history = useTransactions();
  return (
    <>
      {overview.data ? <BalanceCard balance={overview.data.balance} actions={actions} /> : overview.isLoading ? <Loading rows={1} height={110} /> : null}
      {extra}
      <div className="section">
        {history.isLoading ? (
          <Loading rows={5} height={64} />
        ) : history.error || !history.data ? (
          <ErrorState error={history.error} onRetry={history.refetch} />
        ) : (
          <History items={history.data.items} />
        )}
      </div>
    </>
  );
}
