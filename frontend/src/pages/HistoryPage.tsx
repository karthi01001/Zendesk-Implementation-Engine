import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Code,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";

import { api, type AreaDiff, type SnapshotDiff, type SnapshotSummary } from "../api";
import { formatDateTime, previewValue, type Navigate } from "../areas";

interface Props {
  snapshotId: string | null;
  onNavigate: Navigate;
}

function Counts({ area }: { area: AreaDiff }) {
  return (
    <Group gap={6}>
      {area.added.length > 0 && (
        <Badge color="teal" variant="light">
          +{area.added.length} added
        </Badge>
      )}
      {area.removed.length > 0 && (
        <Badge color="red" variant="light">
          −{area.removed.length} removed
        </Badge>
      )}
      {area.changed.length > 0 && (
        <Badge color="yellow" variant="light">
          {area.changed.length} changed
        </Badge>
      )}
      {area.base_status !== area.target_status && (
        <Badge color="gray" variant="outline">
          {area.base_status ?? "not read"} → {area.target_status ?? "not read"}
        </Badge>
      )}
    </Group>
  );
}

export default function HistoryPage({ snapshotId, onNavigate }: Props) {
  const [snapshots, setSnapshots] = useState<SnapshotSummary[] | null>(null);
  const [base, setBase] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [diff, setDiff] = useState<SnapshotDiff | null>(null);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSnapshots(null);
    setDiff(null);
    setError(null);
    api
      .getSnapshots()
      .then((list) => {
        if (cancelled) return;
        setSnapshots(list);
        setTarget(list[0]?.id ?? null);
        setBase(list[1]?.id ?? null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [snapshotId]);

  // Snapshot ids are UTC timestamps (YYYYMMDDTHHMMSSZ), so they sort by time.
  const ordered = base !== null && target !== null && base < target;

  const compare = async () => {
    if (!base || !target) return;
    setComparing(true);
    setError(null);
    try {
      setDiff(await api.compareSnapshots(base, target));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setComparing(false);
    }
  };

  const options = (snapshots ?? []).map((s) => ({
    value: s.id,
    label: `${formatDateTime(s.taken_at)} · ${s.total_items.toLocaleString()} items`,
  }));
  const changedAreas = diff?.areas.filter(
    (a) =>
      a.added.length + a.removed.length + a.changed.length > 0 || a.base_status !== a.target_status,
  );

  return (
    <Stack gap="lg" maw={1100}>
      <div>
        <Title order={2}>History and compare</Title>
        <Text c="dimmed">
          Every "Read everything" is kept on this computer. Compare two reads to see what changed in
          Zendesk in between.
        </Text>
      </div>

      {error && <Alert color="yellow">{error}</Alert>}
      {!snapshots && !error && (
        <Center mih={160}>
          <Loader />
        </Center>
      )}

      {snapshots && snapshots.length === 0 && (
        <Alert color="teal" variant="light" title="No reads yet">
          Go to Overview and click Read everything.
        </Alert>
      )}
      {snapshots && snapshots.length === 1 && (
        <Alert color="teal" variant="light" title="One read so far">
          Read the instance again later (Overview → Read everything again) to compare.
        </Alert>
      )}

      {snapshots && snapshots.length >= 2 && (
        <Group align="flex-end">
          <Select label="From (older)" data={options} value={base} onChange={setBase} w={340} />
          <Select label="To (newer)" data={options} value={target} onChange={setTarget} w={340} />
          <Button onClick={() => void compare()} loading={comparing} disabled={!ordered}>
            Compare
          </Button>
          {base && target && !ordered && (
            <Text size="sm" c="orange">
              Pick an older read in From than in To.
            </Text>
          )}
        </Group>
      )}

      {diff && changedAreas && (
        <Stack gap="sm">
          <Text>
            <b>{diff.added}</b> added, <b>{diff.removed}</b> removed and <b>{diff.changed}</b>{" "}
            changed between {formatDateTime(diff.base_taken_at)} and{" "}
            {formatDateTime(diff.target_taken_at)}.
          </Text>
          {changedAreas.length === 0 ? (
            <Alert color="teal" variant="light">
              No configuration changes between these two reads.
            </Alert>
          ) : (
            <Accordion variant="separated" multiple>
              {changedAreas.map((area) => (
                <Accordion.Item key={area.key} value={area.key}>
                  <Accordion.Control>
                    <Group justify="space-between" pr="md">
                      <Text fw={600}>{area.label}</Text>
                      <Counts area={area} />
                    </Group>
                  </Accordion.Control>
                  <Accordion.Panel>
                    <Stack gap="sm">
                      {area.added.map((item) => (
                        <Group key={`a-${item.id}`} gap="xs">
                          <Badge color="teal" size="xs">
                            added
                          </Badge>
                          <Anchor
                            component="button"
                            size="sm"
                            onClick={() => onNavigate(area.key, { itemId: item.id })}
                          >
                            {item.name}
                          </Anchor>
                        </Group>
                      ))}
                      {area.removed.map((item) => (
                        <Group key={`r-${item.id}`} gap="xs">
                          <Badge color="red" size="xs">
                            removed
                          </Badge>
                          <Text size="sm">{item.name}</Text>
                        </Group>
                      ))}
                      {area.changed.map((item) => (
                        <div key={`c-${item.id}`}>
                          <Group gap="xs" mb={4}>
                            <Badge color="yellow" size="xs">
                              changed
                            </Badge>
                            <Anchor
                              component="button"
                              size="sm"
                              onClick={() => onNavigate(area.key, { itemId: item.id })}
                            >
                              {item.name}
                            </Anchor>
                            {item.truncated && (
                              <Text size="xs" c="dimmed">
                                (first 50 changes shown)
                              </Text>
                            )}
                          </Group>
                          <Table withTableBorder verticalSpacing={4} fz="xs">
                            <Table.Thead>
                              <Table.Tr>
                                <Table.Th w="30%">Setting</Table.Th>
                                <Table.Th>Before</Table.Th>
                                <Table.Th>After</Table.Th>
                              </Table.Tr>
                            </Table.Thead>
                            <Table.Tbody>
                              {item.changes.map((change) => (
                                <Table.Tr key={change.path}>
                                  <Table.Td>
                                    <Code>{change.path}</Code>
                                  </Table.Td>
                                  <Table.Td>{previewValue(change.before)}</Table.Td>
                                  <Table.Td>{previewValue(change.after)}</Table.Td>
                                </Table.Tr>
                              ))}
                            </Table.Tbody>
                          </Table>
                        </div>
                      ))}
                    </Stack>
                  </Accordion.Panel>
                </Accordion.Item>
              ))}
            </Accordion>
          )}
        </Stack>
      )}
    </Stack>
  );
}
