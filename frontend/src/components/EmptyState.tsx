import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}

export function EmptyState({ title, children, action, icon }: EmptyStateProps) {
  return (
    <div className="empty">
      {icon}
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}
