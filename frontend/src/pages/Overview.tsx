import {
  Alert,
  Anchor,
  Button,
  Card,
  Group,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";

import { useState } from "react";

import {
  downloadFile,
  reportUrls,
  type ActiveConnection,
  type AreaInfo,
  type SnapshotSummary,
} from "../api";
import { formatDateTime, groupBySection, summaryFor, type Navigate } from "../areas";
import Findings from "../components/Findings";
import StatusBadge from "../components/StatusBadge";

interface Props {
  connection: ActiveConnection;
  areas: AreaInfo[];
  snapshot: SnapshotSummary | null;
  reading: boolean;
  readError: string | null;
  onReadEverything: () => void;
  onOpenArea: (key: string) => void;
  onNavigate: Navigate;
}

export default function Overview({
  connection,
  areas,
  snapshot,
  reading,
  readError,
  onReadEverything,
  onOpenArea,
  onNavigate,
}: Props) {
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const downloadReport = async () => {
    setDownloading(true);
    setDownloadError(null);
    try {
      await downloadFile(reportUrls.docx, "zendesk-current-state.docx");
    } catch (err) {
      setDownloadError(`The report could not be created: ${(err as Error).message}`);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Stack gap="lg" maw={1100}>
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>{connection.subdomain}.zendesk.com</Title>
          <Text c="dimmed">
            Connected with {connection.auth_type === "oauth" ? "an OAuth client" : "an API token"}
            {connection.scope ? `, scope "${connection.scope}"` : ""}. Reading never changes the
            instance.
          </Text>
        </div>
        <Group>
          {snapshot && (
            <>
              <Button variant="default" loading={downloading} onClick={() => void downloadReport()}>
                Report (Word)
              </Button>
              <Button
                component="a"
                href={reportUrls.html}
                target="_blank"
                rel="noreferrer"
                variant="default"
              >
                Report (print / PDF)
              </Button>
            </>
          )}
          <Button size="md" loading={reading} onClick={onReadEverything}>
            {snapshot ? "Read everything again" : "Read everything"}
          </Button>
        </Group>
      </Group>

      {downloadError && (
        <Alert color="red" withCloseButton onClose={() => setDownloadError(null)}>
          {downloadError}
        </Alert>
      )}

      {readError && (
        <Alert color="red" title="The read did not finish">
          {readError}
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <Card withBorder>
          <Text size="sm" c="dimmed">
            Areas read
          </Text>
          <Text fz={28} fw={700}>
            {snapshot ? `${snapshot.areas_ok} of ${snapshot.areas_total}` : "—"}
          </Text>
        </Card>
        <Card withBorder>
          <Text size="sm" c="dimmed">
            Configuration items
          </Text>
          <Text fz={28} fw={700}>
            {snapshot ? snapshot.total_items.toLocaleString() : "—"}
          </Text>
        </Card>
        <Card withBorder>
          <Text size="sm" c="dimmed">
            Last read
          </Text>
          <Text fz={snapshot ? 20 : 28} fw={700} mt={snapshot ? 6 : 0}>
            {snapshot ? formatDateTime(snapshot.taken_at) : "Never"}
          </Text>
        </Card>
      </SimpleGrid>

      {!snapshot && !reading && (
        <Alert color="teal" variant="light" title="Start by reading the instance">
          Read everything pulls all {areas.length} configuration areas in one pass, usually in under
          a minute, and saves a snapshot on this computer. Nothing in Zendesk is changed.
        </Alert>
      )}

      {snapshot && <Findings snapshotId={snapshot.id} onNavigate={onNavigate} />}

      <div>
        <Title order={4} mb="xs">
          Coverage
        </Title>
        <Table.ScrollContainer minWidth={760}>
          <Table withTableBorder verticalSpacing="xs" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Area</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th ta="right">Items</Table.Th>
                <Table.Th ta="right">Time</Table.Th>
                <Table.Th>Note</Table.Th>
              </Table.Tr>
            </Table.Thead>
            {groupBySection(areas).map((section) => (
              <Table.Tbody key={section.title}>
                <Table.Tr>
                  <Table.Td colSpan={5} bg="var(--mantine-color-default-hover)">
                    <Text size="xs" fw={700} tt="uppercase" c="dimmed">
                      {section.title}
                    </Text>
                  </Table.Td>
                </Table.Tr>
                {section.areas.map((area) => {
                  const summary = summaryFor(snapshot, area.key);
                  return (
                    <Table.Tr key={area.key}>
                      <Table.Td>
                        <Anchor component="button" onClick={() => onOpenArea(area.key)}>
                          {area.label}
                        </Anchor>
                      </Table.Td>
                      <Table.Td>
                        {summary ? (
                          <StatusBadge status={summary.status} />
                        ) : (
                          <Text size="sm" c="dimmed">
                            Not read yet
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td ta="right">
                        {summary?.status === "ok" ? summary.count.toLocaleString() : "—"}
                      </Table.Td>
                      <Table.Td ta="right">
                        {summary ? `${(summary.duration_ms / 1000).toFixed(1)} s` : "—"}
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" c="dimmed">
                          {summary?.message ?? ""}
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            ))}
          </Table>
        </Table.ScrollContainer>
      </div>
    </Stack>
  );
}
