import { Component, type ErrorInfo, type ReactNode } from 'react';

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Pas de télémétrie silencieuse : l'incident reste visible et ne prétend rien avoir réussi.
    console.error('[Kwes] Erreur de rendu', error, info.componentStack);
  }

  override render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page" style={{ padding: 32 }}>
        <h1>Kwes a rencontré un incident d’affichage</h1>
        <p className="notice notice--danger" role="alert" style={{ marginTop: 16 }}>
          {this.state.error.message}
        </p>
        <p className="muted" style={{ marginTop: 12 }}>
          Aucune action n’est considérée comme effectuée. Rechargez l’application pour reprendre ; les
          données seront relues depuis le backend.
        </p>
        <button type="button" className="btn btn--primary" style={{ marginTop: 16 }} onClick={() => window.location.reload()}>
          Recharger Kwes
        </button>
      </div>
    );
  }
}
