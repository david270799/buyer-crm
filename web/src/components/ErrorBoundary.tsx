import { AlertCircle, RefreshCw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** A new value (e.g. the page address) clears the error. */
  resetKey?: string;
}

/** If rendering fails, show what happened and a reload button instead of an empty screen. */
export class ErrorBoundary extends Component<Props, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("CRM: page crashed", error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="state" role="alert">
        <div className="icon">
          <AlertCircle size={22} />
        </div>
        <div>Не удалось показать страницу. Нажмите «Обновить»; если повторяется — пришлите снимок экрана.</div>
        <code className="tiny faint" style={{ wordBreak: "break-word" }}>
          {error.message || String(error)}
        </code>
        <button className="btn small" onClick={() => window.location.reload()}>
          <RefreshCw size={14} /> Обновить
        </button>
      </div>
    );
  }
}
