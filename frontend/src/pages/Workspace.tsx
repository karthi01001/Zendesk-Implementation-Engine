import {
  Alert,
  AppShell,
  Badge,
  Burger,
  Button,
  Center,
  Group,
  Loader,
  NavLink,
  ScrollArea,
  Text,
  Title,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useEffect, useState } from "react";

import { api, type ActiveConnection, type AreaInfo, type SnapshotSummary } from "../api";
import { groupBySection, summaryFor, type Navigate } from "../areas";
import AreaPage from "./AreaPage";
import HistoryPage from "./HistoryPage";
import Overview from "./Overview";
import TagsPage from "./TagsPage";

interface Focus {
  itemId: string | null;
  unusedOnly: boolean;
  nonce: number;
}

interface Props {
  connection: ActiveConnection;
  onDisconnected: () => void;
}

function NavCount({ snapshot, areaKey }: { snapshot: SnapshotSummary | null; areaKey: string }) {
  const summary = summaryFor(snapshot, areaKey);
  if (!summary) return null;
  if (summary.status === "ok") {
    return (
      <Badge size="sm" variant="light" color="gray">
        {summary.count}
      </Badge>
    );
  }
  return (
    <Badge size="xs" variant="outline" color={summary.status === "error" ? "red" : "gray"}>
      {summary.status === "error" ? "error" : "n/a"}
    </Badge>
  );
}

export default function Workspace({ connection, onDisconnected }: Props) {
  const [opened, { toggle, close }] = useDisclosure();
  const [selected, setSelected] = useState("overview");
  const [focus, setFocus] = useState<Focus>({ itemId: null, unusedOnly: false, nonce: 0 });
  const [areas, setAreas] = useState<AreaInfo[] | null>(null);
  const [snapshot, setSnapshot] = useState<SnapshotSummary | null>(null);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.getAreas(), api.getLatestSnapshot()])
      .then(([areaList, latest]) => {
        setAreas(areaList);
        setSnapshot(latest.snapshot);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  const navigate: Navigate = (key, options) => {
    setSelected(key);
    setFocus((previous) => ({
      itemId: options?.itemId ?? null,
      unusedOnly: options?.unusedOnly ?? false,
      nonce: previous.nonce + 1,
    }));
    close(); // collapse the navbar on small screens after choosing an area
    window.scrollTo({ top: 0 });
  };
  const select = (key: string) => navigate(key);

  const readEverything = async () => {
    setReading(true);
    setReadError(null);
    try {
      setSnapshot(await api.readEverything());
    } catch (err) {
      setReadError((err as Error).message);
    } finally {
      setReading(false);
    }
  };

  const disconnect = async () => {
    setLeaving(true);
    setError(null);
    try {
      await api.disconnect();
      onDisconnected();
    } catch (err) {
      setError(`Could not disconnect: ${(err as Error).message}`);
    } finally {
      setLeaving(false);
    }
  };

  const area = areas?.find((item) => item.key === selected);

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 270, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
              aria-label="Toggle navigation"
            />
            <Title order={4}>Zendesk Implementation Engine</Title>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Badge variant="light" size="lg" tt="none">
              {connection.subdomain}.zendesk.com
            </Badge>
            <Button
              variant="subtle"
              color="gray"
              loading={leaving}
              onClick={() => void disconnect()}
            >
              Disconnect
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <AppShell.Section grow component={ScrollArea}>
          <NavLink
            component="button"
            label="Overview"
            active={selected === "overview"}
            onClick={() => select("overview")}
          />
          <Text size="xs" fw={600} c="dimmed" tt="uppercase" mt="md" mb={4} px="sm">
            Explore
          </Text>
          <NavLink
            component="button"
            label="Tags"
            active={selected === "tags"}
            onClick={() => select("tags")}
          />
          <NavLink
            component="button"
            label="History and compare"
            active={selected === "history"}
            onClick={() => select("history")}
          />
          {groupBySection(areas ?? []).map((section) => (
            <div key={section.title}>
              <Text size="xs" fw={600} c="dimmed" tt="uppercase" mt="md" mb={4} px="sm">
                {section.title}
              </Text>
              {section.areas.map((item) => (
                <NavLink
                  key={item.key}
                  component="button"
                  label={item.label}
                  active={selected === item.key}
                  onClick={() => select(item.key)}
                  rightSection={<NavCount snapshot={snapshot} areaKey={item.key} />}
                />
              ))}
            </div>
          ))}
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        {error && (
          <Alert color="red" mb="md" withCloseButton onClose={() => setError(null)}>
            {error}
          </Alert>
        )}
        {areas === null && !error && (
          <Center mih={240}>
            <Loader />
          </Center>
        )}
        {areas !== null && selected === "overview" && (
          <Overview
            connection={connection}
            areas={areas}
            snapshot={snapshot}
            reading={reading}
            readError={readError}
            onReadEverything={() => void readEverything()}
            onOpenArea={select}
            onNavigate={navigate}
          />
        )}
        {selected === "tags" && (
          <TagsPage
            snapshotId={snapshot?.id ?? null}
            focusTag={focus.itemId}
            focusNonce={focus.nonce}
            onNavigate={navigate}
          />
        )}
        {selected === "history" && (
          <HistoryPage snapshotId={snapshot?.id ?? null} onNavigate={navigate} />
        )}
        {area && (
          <AreaPage
            areaKey={area.key}
            label={area.label}
            snapshotId={snapshot?.id ?? null}
            focusId={focus.itemId}
            unusedOnly={focus.unusedOnly}
            focusNonce={focus.nonce}
            onNavigate={navigate}
          />
        )}
      </AppShell.Main>
    </AppShell>
  );
}
