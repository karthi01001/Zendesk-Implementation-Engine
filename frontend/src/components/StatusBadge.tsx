import { Badge } from "@mantine/core";

import type { AreaStatus } from "../api";

const LOOK: Record<AreaStatus, { color: string; label: string }> = {
  ok: { color: "teal", label: "Read" },
  unavailable: { color: "gray", label: "Not available" },
  error: { color: "red", label: "Error" },
};

export default function StatusBadge({ status }: { status: AreaStatus }) {
  const look = LOOK[status];
  return (
    <Badge color={look.color} variant="light" size="sm">
      {look.label}
    </Badge>
  );
}
