import { Bell } from "lucide-react";
import { useEffect, useState } from "react";

import { useEvents, useMarkRead, useUnread } from "../api/hooks";
import { EventFeed } from "../components/events";
import { PageHead } from "../components/Layout";
import { Empty, ErrorState, Loading } from "../components/ui";

export function NotificationsPage() {
  const [important, setImportant] = useState(true);
  const unread = useUnread();
  const feed = useEvents(important);
  const markRead = useMarkRead();
  // Captured once on opening: what was new at that moment stays highlighted
  // and counted on the tabs while the page is open.
  const [opened, setOpened] = useState<{ seenAt: string; important: number; total: number } | null>(null);
  const seenAt = opened?.seenAt;
  const counts = opened;

  useEffect(() => {
    if (opened || !unread.data) return;
    setOpened({
      seenAt: unread.data.seen_at ?? "",
      important: unread.data.important,
      total: unread.data.total,
    });
    if (unread.data.total > 0) markRead.mutate();
  }, [opened, unread.data, markRead]);

  const items = feed.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <>
      <PageHead title="Уведомления" />
      <div className="chips" style={{ marginBottom: 4 }}>
        <button className={`chip ${important ? "active" : ""}`} onClick={() => setImportant(true)}>
          Важные{counts?.important ? ` · ${counts.important}` : ""}
        </button>
        <button className={`chip ${!important ? "active" : ""}`} onClick={() => setImportant(false)}>
          Все{counts?.total ? ` · ${counts.total}` : ""}
        </button>
      </div>
      {feed.isLoading ? (
        <Loading rows={5} height={64} />
      ) : feed.error ? (
        <ErrorState error={feed.error} onRetry={feed.refetch} />
      ) : !items.length ? (
        <Empty
          icon={<Bell size={22} />}
          title={important ? "Важных уведомлений нет" : "Уведомлений пока нет"}
          hint="Здесь появятся выкупы, перезаказы, отправки и комментарии."
        />
      ) : (
        <>
          <EventFeed events={items} unreadAfter={seenAt === undefined ? null : seenAt || "1970-01-01T00:00:00Z"} />
          {feed.hasNextPage && (
            <button
              className="btn block"
              style={{ marginTop: 14 }}
              disabled={feed.isFetchingNextPage}
              onClick={() => feed.fetchNextPage()}
            >
              {feed.isFetchingNextPage ? "Загрузка…" : "Показать ещё"}
            </button>
          )}
        </>
      )}
    </>
  );
}
