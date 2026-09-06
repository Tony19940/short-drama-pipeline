import type { ReactNode } from "react";

type Gate = {
  id: string;
  label: string;
  reason?: string;
  status?: string;
  status_label?: string;
  stale?: boolean;
  locked?: boolean;
  migrated?: boolean;
};

export function AgentShell({
  issues,
  children,
  bottom,
}: {
  previous?: Gate | null;
  current?: Gate | null;
  issues?: string[];
  children: ReactNode;
  bottom?: ReactNode;
}) {
  return (
    <div className="agent-flow">
      {issues?.length ? (
        <div className="flow-alert">
          {issues.slice(0, 4).map((item) => (
            <p key={item}>{item}</p>
          ))}
        </div>
      ) : null}
      <div className="flow-main">{children}</div>
      {bottom ? <p className="flow-note">{bottom}</p> : null}
    </div>
  );
}
