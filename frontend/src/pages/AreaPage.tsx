import {
  Alert,
  Badge,
  Center,
  Group,
  Loader,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useMemo, useState } from "react";

import { api, type AreaData, type ItemRow } from "../api";
import { formatDate, formatDateTime, type Navigate } from "../areas";
import ItemDrawer from "../components/ItemDrawer";
import StatusBadge from "../components/StatusBadge";

interface Props {
  areaKey: string;
  label: string;
  /** Changes whenever a new snapshot is taken, so the page reloads its data. */
  snapshotId: string | null;
  /** Open this item's panel once the data has loaded. */
  focusId?: string | null;
  /** Start with only unused items shown. */
  unusedOnly?: boolean;
  /** Changes on every navigation, so the same focus can be requested twice. */
  focusNonce?: number;
  onNavigate: Navigate;
}

export default function AreaPage({
  areaKey,
  label,
  snapshotId,
  focusId = null,
  unusedOnly = false,
  focusNonce = 0,
  onNavigate,
}: Props) {
  const [data, setData] = useState<AreaData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [onlyUnused, setOnlyUnused] = useState(unusedOnly);
  const [open, setOpen] = useState<ItemRow | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    setOpen(null);
    api
      .getArea(areaKey)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [areaKey, snapshotId]);

  useEffect(() => {
    setQuery("");
    setOnlyUnused(unusedOnly);
  }, [areaKey, unusedOnly, focusNonce]);

  useEffect(() => {
    // Only once this area's own data is in (not the previous area's, still in state).
    if (data && data.key === areaKey && focusId) {
      setOpen(data.items.find((item) => item.id === focusId) ?? null);
    }
  }, [data, areaKey, focusId, focusNonce]);

  const tracksUsage = (data?.items ?? []).some((item) => item.used_by !== null);
  const hasActive = (data?.items ?? []).some((item) => item.active !== null);
  const hasUpdated = (data?.items ?? []).some((item) => item.updated_at !== null);
  const columns = 2 + (hasActive ? 1 : 0) + (tracksUsage ? 1 : 0) + (hasUpdated ? 1 : 0);
  const unusedCount = (data?.items ?? []).filter((item) => item.unused === true).length;
  const unusedKnown = (data?.items ?? []).some((item) => item.unused !== null);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let items = data?.items ?? [];
    if (onlyUnused) items = items.filter((item) => item.unused === true);
    if (!needle) return items;
    return items.filter(
      (item) => item.name.toLowerCase().includes(needle) || item.id.toLowerCase().includes(needle),
    );
  }, [data, query, onlyUnused]);

  return (
    <Stack gap="md" maw={1100}>
      <Group justify="space-between" align="flex-end">
        <div>
          <Group gap="sm">
            <Title order={2}>{label}</Title>
            {data && <StatusBadge status={data.status} />}
          </Group>
          <Text c="dimmed">
            {data
              ? `${data.count.toLocaleString()} items · read ${formatDateTime(data.taken_at)}`
              : " "}
          </Text>
        </div>
        {data?.status === "ok" && data.count > 0 && (
          <Group>
            {tracksUsage && unusedKnown && (
              <Switch
                label={`Unused only (${unusedCount})`}
                checked={onlyUnused}
                onChange={(event) => setOnlyUnused(event.currentTarget.checked)}
              />
            )}
            <TextInput
              placeholder={`Search ${label.toLowerCase()}`}
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
              w={240}
            />
          </Group>
        )}
      </Group>

      {loading && (
        <Center mih={200}>
          <Loader />
        </Center>
      )}

      {error && (
        <Alert color="yellow" title="Nothing to show yet">
          {error}
        </Alert>
      )}

      {data?.status === "unavailable" && (
        <Alert color="gray" title="Not available on this account">
          {data.message}
        </Alert>
      )}
      {data?.status === "error" && (
        <Alert color="red" title="This area could not be read">
          {data.message}
        </Alert>
      )}

      {data?.status === "ok" && (
        <Table.ScrollContainer minWidth={720}>
          <Table striped highlightOnHover withTableBorder verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                {hasActive && <Table.Th>Status</Table.Th>}
                {tracksUsage && <Table.Th ta="right">Used by</Table.Th>}
                {hasUpdated && <Table.Th>Updated</Table.Th>}
                <Table.Th>ID</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((item) => (
                <Table.Tr
                  key={item.id || item.name}
                  onClick={() => setOpen(item)}
                  style={{ cursor: "pointer" }}
                >
                  <Table.Td>
                    <Text fw={500}>{item.name}</Text>
                  </Table.Td>
                  {hasActive && (
                    <Table.Td>
                      {item.active === null ? (
                        "—"
                      ) : (
                        <Badge size="sm" variant="outline" color={item.active ? "teal" : "gray"}>
                          {item.active ? "Active" : "Inactive"}
                        </Badge>
                      )}
                    </Table.Td>
                  )}
                  {tracksUsage && (
                    <Table.Td ta="right">
                      {item.unused ? (
                        <Badge size="sm" variant="light" color="orange">
                          unused
                        </Badge>
                      ) : (
                        item.used_by
                      )}
                    </Table.Td>
                  )}
                  {hasUpdated && <Table.Td>{formatDate(item.updated_at)}</Table.Td>}
                  <Table.Td>
                    <Text size="sm" c="dimmed" ff="monospace">
                      {item.id}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
              {rows.length === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={columns}>
                    <Text c="dimmed" ta="center" py="md">
                      {query || onlyUnused ? "Nothing matches." : "This area is empty."}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      {data?.status === "ok" && tracksUsage && (
        <Text size="xs" c="dimmed">
          "Used by" counts triggers, automations, macros, views, SLA policies, ticket forms and
          other items that refer to each one. Reports and integrations outside Zendesk's
          configuration are not counted, so check before retiring anything.
          {!unusedKnown &&
            " Unused items are not marked because some rule areas were not read; see Findings on the Overview."}
          {areaKey === "ticket-fields" && " System fields such as Subject are never marked unused."}
        </Text>
      )}

      <ItemDrawer
        area={areaKey}
        itemId={open?.id ?? null}
        title={open?.name ?? ""}
        raw={open?.raw ?? null}
        onClose={() => setOpen(null)}
        preferUses={!tracksUsage}
        onNavigate={(key, options) => {
          setOpen(null);
          onNavigate(key, options);
        }}
      />
    </Stack>
  );
}
