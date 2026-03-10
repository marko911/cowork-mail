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
  fetchThread,
} from "./db.js";
import http from "http";

const PORT = parseInt(process.env.COWORK_MAIL_PORT || "3141", 10);
const AUTH_TOKEN = process.env.COWORK_MAIL_TOKEN || "";

// --- MCP Server factory ---

function createServer(): McpServer {
  const server = new McpServer({
    name: "cowork-mail",
    version: "0.1.0",
  });

  server.tool(
    "register_persona",
    "Register or update a persona in a project. Call at session start to announce presence.",
    {
      persona_id: z.string().describe("Unique persona identifier (e.g. 'north', 'south')"),
      project_key: z.string().describe("Shared project namespace all teammates use"),
      display_name: z.string().describe("Human-readable name for this persona"),
      role: z.string().optional().describe("Optional role description"),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(registerPersona(args), null, 2) }],
    })
  );

  server.tool(
    "list_personas",
    "List all registered personas in a project. Use to discover teammates.",
    {
      project_key: z.string().describe("Project namespace to list personas for"),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(listPersonas(args.project_key), null, 2) }],
    })
  );

  server.tool(
    "send_message",
    "Send a message to one or more personas. Supports threads via thread_id.",
    {
      project_key: z.string(),
      from_persona: z.string().describe("Your persona_id"),
      to: z.array(z.string()).describe("Array of recipient persona_ids"),
      subject: z.string(),
      body: z.string().describe("Message content"),
      thread_id: z.string().optional().describe("Optional thread ID to group related messages"),
      in_reply_to: z.string().optional().describe("Optional message_id this is replying to"),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(sendMessage(args), null, 2) }],
    })
  );

  server.tool(
    "fetch_inbox",
    "Fetch messages from your inbox. Returns unacked messages by default. Marks fetched as read.",
    {
      project_key: z.string(),
      persona_id: z.string().describe("Your persona_id"),
      limit: z.number().optional().describe("Max messages to return (default 50)"),
      unread_only: z.boolean().optional().describe("If true, only return unread messages"),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(fetchInbox(args), null, 2) }],
    })
  );

  server.tool(
    "ack_message",
    "Acknowledge a specific message, removing it from your active inbox.",
    {
      project_key: z.string(),
      persona_id: z.string(),
      message_id: z.string(),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(ackMessage(args), null, 2) }],
    })
  );

  server.tool(
    "ack_all",
    "Acknowledge all messages in your inbox at once.",
    {
      project_key: z.string(),
      persona_id: z.string(),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(ackAll(args), null, 2) }],
    })
  );

  server.tool(
    "get_unread_count",
    "Get count of unread messages. Used by polling watcher to check for new mail.",
    {
      project_key: z.string(),
      persona_id: z.string(),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(getUnreadCount(args), null, 2) }],
    })
  );

  server.tool(
    "fetch_thread",
    "Fetch all messages in a thread, ordered chronologically.",
    {
      project_key: z.string(),
      thread_id: z.string(),
    },
    async (args) => ({
      content: [{ type: "text", text: JSON.stringify(fetchThread(args), null, 2) }],
    })
  );

  return server;
}

// --- REST endpoints for polling watcher (no MCP overhead) ---

function handleRestApi(
  req: http.IncomingMessage,
  res: http.ServerResponse
): boolean {
  const url = new URL(req.url || "/", `http://localhost:${PORT}`);

  if (req.method === "GET" && url.pathname === "/api/unread") {
    const project_key = url.searchParams.get("project_key");
    const persona_id = url.searchParams.get("persona_id");

    if (!project_key || !persona_id) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "project_key and persona_id required" }));
      return true;
    }

    const result = getUnreadCount({ project_key, persona_id });
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(result));
    return true;
  }

  if (req.method === "GET" && url.pathname === "/api/personas") {
    const project_key = url.searchParams.get("project_key");
    if (!project_key) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "project_key required" }));
      return true;
    }
    const result = listPersonas(project_key);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(result));
    return true;
  }

  if (req.method === "GET" && url.pathname === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", server: "cowork-mail", version: "0.1.0" }));
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

  res.writeHead(401, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "unauthorized" }));
  return false;
}

// --- HTTP Server ---

const httpServer = http.createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, Mcp-Session-Id");
  res.setHeader("Access-Control-Expose-Headers", "Mcp-Session-Id");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  const url = new URL(req.url || "/", `http://localhost:${PORT}`);

  // Auth check (skip health)
  if (url.pathname !== "/health") {
    if (!checkAuth(req, res)) return;
  }

  // REST API
  if (handleRestApi(req, res)) return;

  // MCP Streamable HTTP — stateless: new server+transport per request
  if (url.pathname === "/mcp") {
    try {
      const mcpServer = createServer();
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
      });
      await mcpServer.connect(transport);
      await transport.handleRequest(req, res);
      await transport.close();
      await mcpServer.close();
    } catch (err: unknown) {
      if (!res.headersSent) {
        const message = err instanceof Error ? err.message : String(err);
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: message }));
      }
    }
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      error: "not found",
      endpoints: ["/mcp", "/api/unread", "/api/personas", "/health"],
    })
  );
});

httpServer.listen(PORT, () => {
  console.log(`cowork-mail MCP server listening on http://0.0.0.0:${PORT}`);
  console.log(`  MCP endpoint:  POST http://localhost:${PORT}/mcp`);
  console.log(`  REST unread:   GET  http://localhost:${PORT}/api/unread?project_key=X&persona_id=Y`);
  console.log(`  REST personas: GET  http://localhost:${PORT}/api/personas?project_key=X`);
  console.log(`  Health:        GET  http://localhost:${PORT}/health`);
  if (!AUTH_TOKEN) {
    console.log(`  Warning: No COWORK_MAIL_TOKEN set — running in open/dev mode`);
  }
});

process.on("SIGINT", () => {
  console.log("\nShutting down...");
  httpServer.close();
  process.exit(0);
});
