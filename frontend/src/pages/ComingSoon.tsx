// No longer used since Phase 1 (every area now has a reader). Safe to delete.
import { Center, Stack, Text, Title } from "@mantine/core";

export default function ComingSoon({ label }: { label: string }) {
  return (
    <Center mih={320}>
      <Stack align="center" gap={4}>
        <Title order={3}>{label}</Title>
        <Text c="dimmed">This area is not available yet.</Text>
      </Stack>
    </Center>
  );
}
