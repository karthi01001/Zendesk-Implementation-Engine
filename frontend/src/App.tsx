import { Alert, Button, Center, Loader, Stack } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";

import { api, type ActiveConnection } from "./api";
import ConnectPage from "./pages/ConnectPage";
import Workspace from "./pages/Workspace";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; connection: ActiveConnection };

export default function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", connection: await api.getConnection() });
    } catch (error) {
      setState({ kind: "error", message: (error as Error).message });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.kind === "loading") {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }

  if (state.kind === "error") {
    return (
      <Center h="100vh" p="md">
        <Stack maw={480}>
          <Alert color="red" title="Can't reach the engine">
            {state.message}
          </Alert>
          <Button variant="default" onClick={() => void load()}>
            Try again
          </Button>
        </Stack>
      </Center>
    );
  }

  if (!state.connection.active) {
    return <ConnectPage onConnected={() => void load()} />;
  }

  return <Workspace connection={state.connection} onDisconnected={() => void load()} />;
}
