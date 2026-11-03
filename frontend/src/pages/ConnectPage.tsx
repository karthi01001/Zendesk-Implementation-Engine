import {
  Alert,
  Button,
  Container,
  Group,
  List,
  Paper,
  PasswordInput,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useState, type FormEvent } from "react";

import { api, type AuthType, type ConnectionInfo, type ConnectRequest } from "../api";

interface Props {
  onConnected: () => void;
}

type Result =
  | { kind: "none" }
  | { kind: "ok"; info: ConnectionInfo }
  | { kind: "error"; message: string };

export default function ConnectPage({ onConnected }: Props) {
  const [subdomain, setSubdomain] = useState("");
  const [authType, setAuthType] = useState<AuthType>("oauth");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [email, setEmail] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [busy, setBusy] = useState<"test" | "connect" | null>(null);
  const [result, setResult] = useState<Result>({ kind: "none" });

  const body = (): ConnectRequest =>
    authType === "oauth"
      ? { subdomain, auth_type: "oauth", client_id: clientId, client_secret: clientSecret }
      : { subdomain, auth_type: "api_token", email, api_token: apiToken };

  const complete =
    subdomain.trim() !== "" &&
    (authType === "oauth"
      ? clientId.trim() !== "" && clientSecret.trim() !== ""
      : email.trim() !== "" && apiToken.trim() !== "");

  const run = async (mode: "test" | "connect") => {
    setBusy(mode);
    setResult({ kind: "none" });
    try {
      const info = mode === "test" ? await api.testConnection(body()) : await api.connect(body());
      setResult({ kind: "ok", info });
      if (mode === "connect") onConnected();
    } catch (error) {
      setResult({ kind: "error", message: (error as Error).message });
    } finally {
      setBusy(null);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (complete) void run("connect");
  };

  return (
    <Container size={520} py={64}>
      <Stack gap="lg">
        <div>
          <Title order={2}>Connect to a Zendesk instance</Title>
          <Text c="dimmed" mt={4}>
            The engine reads the instance's configuration with read-only access. Credentials stay in
            Windows Credential Manager on this computer.
          </Text>
        </div>

        <Paper withBorder p="xl" component="form" onSubmit={submit}>
          <Stack>
            <TextInput
              label="Zendesk subdomain"
              placeholder="pdi-nagarro6612"
              value={subdomain}
              onChange={(event) => setSubdomain(event.currentTarget.value)}
              rightSection={
                <Text size="sm" c="dimmed">
                  .zendesk.com
                </Text>
              }
              rightSectionWidth={110}
              required
              autoFocus
            />

            <SegmentedControl
              fullWidth
              value={authType}
              onChange={(value) => setAuthType(value as AuthType)}
              data={[
                { label: "OAuth client", value: "oauth" },
                { label: "API token (legacy)", value: "api_token" },
              ]}
            />

            {authType === "oauth" ? (
              <>
                <TextInput
                  label="OAuth client identifier"
                  value={clientId}
                  onChange={(event) => setClientId(event.currentTarget.value)}
                  required
                />
                <PasswordInput
                  label="OAuth client secret"
                  value={clientSecret}
                  onChange={(event) => setClientSecret(event.currentTarget.value)}
                  required
                />
                <Text size="xs" c="dimmed">
                  Create it in Admin Center → Apps and integrations → APIs → OAuth clients, signed
                  in as the service-account admin. Client kind: Confidential.
                </Text>
              </>
            ) : (
              <>
                <Alert color="yellow" variant="light">
                  Zendesk no longer issues new API tokens and turns off existing ones on 30 Apr
                  2027. Use this only for accounts that still have an active token.
                </Alert>
                <TextInput
                  label="Admin email"
                  value={email}
                  onChange={(event) => setEmail(event.currentTarget.value)}
                  required
                />
                <PasswordInput
                  label="API token"
                  value={apiToken}
                  onChange={(event) => setApiToken(event.currentTarget.value)}
                  required
                />
              </>
            )}

            {result.kind === "error" && (
              <Alert color="red" title="Connection failed">
                {result.message}
              </Alert>
            )}
            {result.kind === "ok" && (
              <Alert
                color={result.info.warnings.length ? "yellow" : "teal"}
                title="Connection works"
              >
                <Text size="sm">
                  {result.info.subdomain}.zendesk.com, acting as {result.info.user_name} (
                  {result.info.role}).
                </Text>
                {result.info.warnings.length > 0 && (
                  <List size="sm" mt="xs">
                    {result.info.warnings.map((warning) => (
                      <List.Item key={warning}>{warning}</List.Item>
                    ))}
                  </List>
                )}
              </Alert>
            )}

            <Group justify="flex-end">
              <Button
                variant="default"
                disabled={!complete}
                loading={busy === "test"}
                onClick={() => void run("test")}
              >
                Test connection
              </Button>
              <Button type="submit" disabled={!complete} loading={busy === "connect"}>
                Connect
              </Button>
            </Group>
          </Stack>
        </Paper>
      </Stack>
    </Container>
  );
}
