import { Anchor, Badge, Button, Card, Group, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";

import { api, type DependencySummary } from "../api";
import type { Navigate } from "../areas";

interface Props {
  snapshotId: string;
  onNavigate: Navigate;
}

const SHOWN = 8;

/** What the dependency index found in the latest read: unused fields and broken references. */
export default function Findings({ snapshotId, onNavigate }: Props) {
  const [summary, setSummary] = useState<DependencySummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSummary(null);
    setError(null);
    api
      .getDependencySummary()
      .then((result) => {
        if (!cancelled) setSummary(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [snapshotId]);

  if (error) {
    return (
      <Text size="sm" c="red">
        Could not load findings: {error}
      </Text>
    );
  }
  if (!summary) return null;

  const unused = summary.unused_ticket_fields.length;
  const broken = summary.broken;

  return (
    <div>
      <Title order={4} mb="xs">
        Findings
      </Title>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder>
          <Group justify="space-between" align="flex-start">
            <div>
              <Text size="sm" c="dimmed">
                Unused custom ticket fields
              </Text>
              <Text fz={28} fw={700}>
                {summary.incomplete_areas.length ? "—" : unused}
              </Text>
              <Text size="xs" c="dimmed">
                {summary.incomplete_areas.length
                  ? `Can't be checked: ${summary.incomplete_areas.join(", ")} not read.`
                  : "Not referred to by any trigger, automation, macro, view, SLA policy or form."}
              </Text>
            </div>
            {unused > 0 && (
              <Button
                variant="light"
                size="xs"
                onClick={() => onNavigate("ticket-fields", { unusedOnly: true })}
              >
                Show them
              </Button>
            )}
          </Group>
        </Card>
        <Card withBorder>
          <Text size="sm" c="dimmed">
            References to missing items
          </Text>
          <Text fz={28} fw={700} c={broken.length ? "red" : undefined}>
            {broken.length}
          </Text>
          {broken.length === 0 ? (
            <Text size="xs" c="dimmed">
              Every rule refers to items that exist.
            </Text>
          ) : (
            <Stack gap={4} mt={4}>
              {broken.slice(0, SHOWN).map((ref, index) => (
                <Group key={index} gap={6} wrap="nowrap">
                  <Anchor
                    size="sm"
                    component="button"
                    onClick={() => onNavigate(ref.source.area, { itemId: ref.source.id })}
                  >
                    {ref.source.name}
                  </Anchor>
                  <Text size="xs" c="dimmed" truncate>
                    → {ref.target.label} {ref.target.id}
                  </Text>
                  <Badge size="xs" variant="outline" color="gray">
                    {ref.context}
                  </Badge>
                </Group>
              ))}
              {broken.length > SHOWN && (
                <Text size="xs" c="dimmed">
                  …and {broken.length - SHOWN} more (all listed in the report)
                </Text>
              )}
            </Stack>
          )}
        </Card>
      </SimpleGrid>
      <Text size="xs" c="dimmed" mt={6}>
        {summary.references.toLocaleString()} references and {summary.tags.toLocaleString()} tags
        indexed from the latest read.
      </Text>
    </div>
  );
}
