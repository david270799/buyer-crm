import type { ReactNode } from "react";

import { useOverview, useTransactions } from "../api/hooks";
import { PageHead } from "../components/Layout";
import { BalanceCard, History } from "../components/money";
import { ErrorState, Loading } from "../components/ui";

export function BalancePage({
  title = "История баланса",
  actions,
  extra,
}: {
  title?: string;
  actions?: ReactNode;
  /** Shown between the balance card and the history (admin: own profit). */
  extra?: ReactNode;
}) {
  const overview = useOverview();
  const history = useTransactions();
  return (
    <>
      <PageHead title={title} action={actions} />
      {overview.data ? <BalanceCard balance={overview.data.balance} /> : overview.isLoading ? <Loading rows={1} height={110} /> : null}
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
