import { Anchor, Badge, Group, Stack, Text } from "@mantine/core";

import type { ItemKey, Reference } from "../api";
import type { Navigate } from "../areas";

interface Props {
  references: Reference[];
  /** Which end of each reference to list: the items that use this one, or the ones it uses. */
  show: "source" | "target";
  onNavigate: Navigate;
  empty: string;
}

export default function ReferenceList({ references, show, onNavigate, empty }: Props) {
  if (references.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        {empty}
      </Text>
    );
  }

  const groups = new Map<string, Reference[]>();
  for (const ref of references) {
    const label = ref[show].label;
    groups.set(label, [...(groups.get(label) ?? []), ref]);
  }

  const open = (item: ItemKey) => {
    if (!item.missing) onNavigate(item.area, { itemId: item.id });
  };

  return (
    <Stack gap="md">
      {[...groups.entries()].map(([label, refs]) => (
        <div key={label}>
          <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={4}>
            {label} ({refs.length})
          </Text>
          <Stack gap={6}>
            {refs.map((ref, index) => {
              const item = ref[show];
              return (
                <Group
                  key={`${item.area}:${item.id}:${ref.context}:${index}`}
                  gap="xs"
                  wrap="nowrap"
                >
                  {item.missing ? (
                    <Text size="sm" c="red">
                      {item.name}
                    </Text>
                  ) : (
                    <Anchor size="sm" component="button" onClick={() => open(item)}>
                      {item.name}
                    </Anchor>
                  )}
                  {item.missing && (
                    <Badge size="xs" color="red" variant="light">
                      missing
                    </Badge>
                  )}
                  <Badge size="xs" variant="outline" color="gray">
                    {ref.context}
                  </Badge>
                  {ref.detail && (
                    <Text size="xs" c="dimmed" truncate>
                      {ref.detail}
                    </Text>
                  )}
                </Group>
              );
            })}
          </Stack>
        </div>
      ))}
    </Stack>
  );
}
