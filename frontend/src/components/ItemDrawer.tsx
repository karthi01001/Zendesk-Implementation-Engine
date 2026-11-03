import { Alert, Code, Drawer, Loader, ScrollArea, Tabs, Text } from "@mantine/core";
import { useEffect, useRef, useState } from "react";

import { api, type ItemDependencies } from "../api";
import type { Navigate } from "../areas";
import ReferenceList from "./ReferenceList";

interface Props {
  area: string;
  itemId: string | null;
  title: string;
  raw: Record<string, unknown> | null;
  onClose: () => void;
  onNavigate: Navigate;
  /** Open on "Uses" (for rules, which use things) instead of "Used by". */
  preferUses?: boolean;
}

/** Side panel for one item: where it is used, what it uses, and its raw JSON. */
export default function ItemDrawer({
  area,
  itemId,
  title,
  raw,
  onClose,
  onNavigate,
  preferUses = false,
}: Props) {
  const [deps, setDeps] = useState<ItemDependencies | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Keep showing the last item while the drawer animates closed.
  const last = useRef({ itemId, title, raw });
  if (itemId !== null) last.current = { itemId, title, raw };
  const shown = last.current;

  useEffect(() => {
    if (itemId === null) return;
    let cancelled = false;
    setDeps(null);
    setError(null);
    api
      .getDependencies(area, itemId)
      .then((result) => {
        if (!cancelled) setDeps(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [area, itemId]);

  const usedBy = deps?.used_by.length ?? 0;
  const uses = deps?.uses.length ?? 0;
  const broken = deps?.uses.filter((ref) => ref.target.missing).length ?? 0;

  return (
    <Drawer
      opened={itemId !== null}
      onClose={onClose}
      position="right"
      size="xl"
      title={<Text fw={600}>{shown.title}</Text>}
      scrollAreaComponent={ScrollArea.Autosize}
    >
      {error && (
        <Alert color="red" mb="md">
          {error}
        </Alert>
      )}
      <Tabs
        key={shown.itemId ?? ""}
        defaultValue={preferUses && shown.raw ? "uses" : "used-by"}
        keepMounted={false}
      >
        <Tabs.List mb="md">
          <Tabs.Tab value="used-by">Used by {deps ? `(${usedBy})` : ""}</Tabs.Tab>
          {shown.raw && (
            <Tabs.Tab value="uses" color={broken ? "red" : undefined}>
              Uses {deps ? `(${uses}${broken ? `, ${broken} missing` : ""})` : ""}
            </Tabs.Tab>
          )}
          {shown.raw && <Tabs.Tab value="json">JSON</Tabs.Tab>}
        </Tabs.List>

        <Tabs.Panel value="used-by">
          {deps ? (
            <ReferenceList
              references={deps.used_by}
              show="source"
              onNavigate={onNavigate}
              empty="Nothing in the latest read refers to this item."
            />
          ) : (
            !error && <Loader size="sm" />
          )}
        </Tabs.Panel>
        {shown.raw && (
          <Tabs.Panel value="uses">
            {deps ? (
              <ReferenceList
                references={deps.uses}
                show="target"
                onNavigate={onNavigate}
                empty="This item does not refer to other configuration items."
              />
            ) : (
              !error && <Loader size="sm" />
            )}
          </Tabs.Panel>
        )}
        {shown.raw && (
          <Tabs.Panel value="json">
            <Text size="sm" c="dimmed" mb="xs">
              Exactly as Zendesk returned it.
            </Text>
            <Code block>{JSON.stringify(shown.raw, null, 2)}</Code>
          </Tabs.Panel>
        )}
      </Tabs>
    </Drawer>
  );
}
