import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";
import {
  registerPersona,
  listPersonas,
  sendMessage,
  fetchInbox,
  ackMessage,
  ackAll,
  getUnreadCount,
} from "./db.js";
import http from "http";

const PORT = parseInt(process.env.COWORK_MAIL_PORT || "3141", 10);
const AUTH_TOKEN = process.env.COWORK_MAIL_TOKEN || "";

// --- MCP Server ---

function createServer(): McpServer {
  const server = new McpServer({ name: "cowork-mail", version: "0.2.0" });

  server.tool(
    "register_persona",
    "Register or update your persona. Call at session start.",
    {
      persona_id: z.string().describe("Your unique persona ID"),
      display_name: z.string().optional().describe("Human-readable name"),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(registerPersona(args.persona_id, args.display_name)) }],
    })
  );

  server.tool(
    "list_personas",
    "List all registered personas.",
    {},
    async () => ({
      content: [{ type: "text", text: JSON.stringify(listPersonas(), null, 2) }],
    })
  );

  server.tool(
    "send_message",
    "Send a JSON message to one or more personas.",
    {
      from_persona: z.string().describe("Your persona_id"),
      to: z.array(z.string()).describe("Recipient persona_id(s)"),
      payload: z.any().describe("JSON payload — put all message content here"),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(sendMessage(args.from_persona, args.to, args.payload)) }],
    })
  );

  server.tool(
    "fetch_inbox",
    "Fetch messages from your inbox. Marks fetched messages as read.",
    {
      persona_id: z.string().describe("Your persona_id"),
      limit: z.number().optional().describe("Max messages (default 50)"),
      unread_only: z.boolean().optional().describe("Only unread messages"),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(fetchInbox(args.persona_id, args.limit, args.unread_only), null, 2) }],
    })
  );

  server.tool(
    "ack_message",
    "Acknowledge a message, removing it from active inbox.",
    {
      persona_id: z.string(),
      message_id: z.string(),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(ackMessage(args.persona_id, args.message_id)) }],
    })
  );

  server.tool(
    "ack_all",
    "Acknowledge all messages in your inbox.",
    {
      persona_id: z.string(),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(ackAll(args.persona_id)) }],
    })
  );

  server.tool(
    "get_unread_count",
    "Get count of unread messages.",
    {
      persona_id: z.string(),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(getUnreadCount(args.persona_id)) }],
    })
  );

  return server;
}

// --- REST API ---

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    let body = "";
    req.on("data", (chunk: Buffer) => { body += chunk.toString(); });
    req.on("end", () => resolve(body));
  });
}

function json(res: http.ServerResponse, status: number, data: unknown) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}

async function handleRest(req: http.IncomingMessage, res: http.ServerResponse): Promise<boolean> {
  const url = new URL(req.url || "/", `http://localhost:${PORT}`);
  const p = url.pathname;
  const q = (k: string) => url.searchParams.get(k);

  if (p === "/health") {
    json(res, 200, { status: "ok", server: "cowork-mail", version: "0.2.0" });
    return true;
  }

  if (req.method === "GET" && p === "/api/unread") {
    const persona_id = q("persona_id");
    if (!persona_id) { json(res, 400, { error: "persona_id required" }); return true; }
    json(res, 200, getUnreadCount(persona_id));
    return true;
  }

  if (req.method === "GET" && p === "/api/personas") {
    json(res, 200, listPersonas());
    return true;
  }

  if (req.method === "GET" && p === "/api/inbox") {
    const persona_id = q("persona_id");
    if (!persona_id) { json(res, 400, { error: "persona_id required" }); return true; }
    const limit = parseInt(q("limit") || "50", 10);
    const unread_only = q("unread_only") === "true";
    json(res, 200, fetchInbox(persona_id, limit, unread_only));
    return true;
  }

  if (req.method === "POST" && p === "/api/register") {
    try {
      const body = JSON.parse(await readBody(req));
      if (!body.persona_id) { json(res, 400, { error: "persona_id required" }); return true; }
      json(res, 200, registerPersona(body.persona_id, body.display_name));
    } catch (e: unknown) {
      json(res, 400, { error: e instanceof Error ? e.message : String(e) });
    }
    return true;
  }

  if (req.method === "POST" && p === "/api/send") {
    try {
      const body = JSON.parse(await readBody(req));
      if (!body.from_persona || !body.to || !body.payload) {
        json(res, 400, { error: "from_persona, to, payload required" });
        return true;
      }
      const to = Array.isArray(body.to) ? body.to : [body.to];
      json(res, 200, sendMessage(body.from_persona, to, body.payload));
    } catch (e: unknown) {
      json(res, 400, { error: e instanceof Error ? e.message : String(e) });
    }
    return true;
  }

  if (req.method === "POST" && p === "/api/ack") {
    try {
      const body = JSON.parse(await readBody(req));
      if (!body.persona_id) { json(res, 400, { error: "persona_id required" }); return true; }
      const result = body.message_id
        ? ackMessage(body.persona_id, body.message_id)
        : ackAll(body.persona_id);
      json(res, 200, result);
    } catch (e: unknown) {
      json(res, 400, { error: e instanceof Error ? e.message : String(e) });
    }
    return true;
  }

  return false;
}

// --- Auth ---

function checkAuth(req: http.IncomingMessage, res: http.ServerResponse): boolean {
  if (!AUTH_TOKEN) return true;
  const authHeader = req.headers.authorization;
  if (authHeader === `Bearer ${AUTH_TOKEN}`) return true;
  const url = new URL(req.url || "/", `http://localhost:${PORT}`);
  if (url.searchParams.get("token") === AUTH_TOKEN) return true;
  json(res, 401, { error: "unauthorized" });
  return false;
}

// --- HTTP Server ---

const httpServer = http.createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, Mcp-Session-Id");
  res.setHeader("Access-Control-Expose-Headers", "Mcp-Session-Id");

  if (req.method === "OPTIONS") { res.writeHead(204); res.end(); return; }

  const url = new URL(req.url || "/", `http://localhost:${PORT}`);
  if (url.pathname !== "/health" && !checkAuth(req, res)) return;
  if (await handleRest(req, res)) return;

  if (url.pathname === "/mcp") {
    try {
      const mcpServer = createServer();
      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
      await mcpServer.connect(transport);
      await transport.handleRequest(req, res);
      await transport.close();
      await mcpServer.close();
    } catch (err: unknown) {
      if (!res.headersSent) {
        json(res, 500, { error: err instanceof Error ? err.message : String(err) });
      }
    }
    return;
  }

  json(res, 404, { error: "not found", endpoints: ["/mcp", "/api/unread", "/api/personas", "/api/inbox", "/api/send", "/api/register", "/api/ack", "/health"] });
});

httpServer.listen(PORT, () => {
  console.log(`cowork-mail v0.2.0 on http://0.0.0.0:${PORT}`);
  if (!AUTH_TOKEN) console.log("  Warning: No COWORK_MAIL_TOKEN set — open mode");
});

process.on("SIGINT", () => { httpServer.close(); process.exit(0); });
