import { Alert, Center, Group, Loader, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useEffect, useMemo, useState } from "react";

import { api, type TagUsage } from "../api";
import type { Navigate } from "../areas";
import ItemDrawer from "../components/ItemDrawer";

interface Props {
  snapshotId: string | null;
  focusTag?: string | null;
  focusNonce?: number;
  onNavigate: Navigate;
}

/** Every tag the configuration sets, checks or offers through dropdown options. */
export default function TagsPage({
  snapshotId,
  focusTag = null,
  focusNonce = 0,
  onNavigate,
}: Props) {
  const [tags, setTags] = useState<TagUsage[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTags(null);
    setError(null);
    api
      .getTags()
      .then((result) => {
        if (!cancelled) setTags(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [snapshotId]);

  useEffect(() => {
    if (focusTag) setOpen(focusTag);
  }, [focusTag, focusNonce]);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (tags ?? []).filter((t) => !needle || t.tag.toLowerCase().includes(needle));
  }, [tags, query]);

  return (
    <Stack gap="md" maw={900}>
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Tags</Title>
          <Text c="dimmed">
            {tags
              ? `${tags.length.toLocaleString()} tags set, checked or offered by dropdown fields`
              : " "}
          </Text>
        </div>
        <TextInput
          placeholder="Search tags"
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          w={260}
        />
      </Group>

      {error && (
        <Alert color="yellow" title="Nothing to show yet">
          {error}
        </Alert>
      )}
      {!tags && !error && (
        <Center mih={200}>
          <Loader />
        </Center>
      )}

      {tags && (
        <Table striped highlightOnHover withTableBorder verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Tag</Table.Th>
              <Table.Th ta="right">Used by</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((t) => (
              <Table.Tr key={t.tag} onClick={() => setOpen(t.tag)} style={{ cursor: "pointer" }}>
                <Table.Td>
                  <Text ff="monospace" size="sm">
                    {t.tag}
                  </Text>
                </Table.Td>
                <Table.Td ta="right">{t.used_by}</Table.Td>
              </Table.Tr>
            ))}
            {rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={2}>
                  <Text c="dimmed" ta="center" py="md">
                    No tags match.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      )}

      <ItemDrawer
        area="tags"
        itemId={open}
        title={open ? `Tag: ${open}` : ""}
        raw={null}
        onClose={() => setOpen(null)}
        onNavigate={(key, options) => {
          setOpen(null);
          onNavigate(key, options);
        }}
      />
    </Stack>
  );
}
