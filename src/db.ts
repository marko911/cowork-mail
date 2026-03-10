import { Database } from "bun:sqlite";
import path from "path";

const DB_PATH = process.env.COWORK_MAIL_DB || path.join(process.cwd(), "cowork-mail.db");

const db = new Database(DB_PATH, { create: true });

db.run("PRAGMA journal_mode = WAL");
db.run("PRAGMA foreign_keys = ON");

db.run(`
  CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL,
    project_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT,
    registered_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(persona_id, project_key)
  )
`);

db.run(`
  CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    project_key TEXT NOT NULL,
    from_persona TEXT NOT NULL,
    to_persona TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    thread_id TEXT,
    in_reply_to TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    read_at TEXT,
    acked_at TEXT
  )
`);

db.run(`CREATE INDEX IF NOT EXISTS idx_messages_inbox ON messages(project_key, to_persona, acked_at)`);
db.run(`CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id)`);
db.run(`CREATE INDEX IF NOT EXISTS idx_messages_unread ON messages(project_key, to_persona, read_at)`);

// --- Persona operations ---

const stmtRegister = db.prepare(`
  INSERT INTO personas (persona_id, project_key, display_name, role)
  VALUES ($persona_id, $project_key, $display_name, $role)
  ON CONFLICT(persona_id, project_key) DO UPDATE SET
    display_name = $display_name,
    role = COALESCE($role, personas.role),
    last_seen_at = datetime('now')
`);

const stmtListPersonas = db.prepare(`
  SELECT persona_id, display_name, role, registered_at, last_seen_at
  FROM personas WHERE project_key = $project_key
  ORDER BY persona_id
`);

const stmtTouchPersona = db.prepare(`
  UPDATE personas SET last_seen_at = datetime('now')
  WHERE persona_id = $persona_id AND project_key = $project_key
`);

export function registerPersona(params: {
  persona_id: string;
  project_key: string;
  display_name: string;
  role?: string;
}) {
  stmtRegister.run({
    $persona_id: params.persona_id,
    $project_key: params.project_key,
    $display_name: params.display_name,
    $role: params.role ?? null,
  });
  return { ok: true, persona_id: params.persona_id };
}

export function listPersonas(project_key: string) {
  return stmtListPersonas.all({ $project_key: project_key });
}

export function touchPersona(persona_id: string, project_key: string) {
  stmtTouchPersona.run({ $persona_id: persona_id, $project_key: project_key });
}

// --- Message operations ---

function generateMessageId(): string {
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 8);
  return `msg_${ts}_${rand}`;
}

const stmtInsertMessage = db.prepare(`
  INSERT INTO messages (message_id, project_key, from_persona, to_persona, subject, body, thread_id, in_reply_to)
  VALUES ($message_id, $project_key, $from_persona, $to_persona, $subject, $body, $thread_id, $in_reply_to)
`);

export function sendMessage(params: {
  project_key: string;
  from_persona: string;
  to: string[];
  subject: string;
  body: string;
  thread_id?: string;
  in_reply_to?: string;
}) {
  const ids: string[] = [];
  const tx = db.transaction(() => {
    for (const to_persona of params.to) {
      const message_id = generateMessageId();
      stmtInsertMessage.run({
        $message_id: message_id,
        $project_key: params.project_key,
        $from_persona: params.from_persona,
        $to_persona: to_persona,
        $subject: params.subject,
        $body: params.body,
        $thread_id: params.thread_id ?? null,
        $in_reply_to: params.in_reply_to ?? null,
      });
      ids.push(message_id);
    }
    touchPersona(params.from_persona, params.project_key);
  });
  tx();
  return { ok: true, message_ids: ids, recipients: params.to };
}

const stmtFetchInbox = db.prepare(`
  SELECT message_id, from_persona, to_persona, subject, body, thread_id, in_reply_to, created_at, read_at, acked_at
  FROM messages
  WHERE project_key = $project_key AND to_persona = $persona_id AND acked_at IS NULL
  ORDER BY created_at DESC
  LIMIT $limit
`);

const stmtFetchInboxUnread = db.prepare(`
  SELECT message_id, from_persona, to_persona, subject, body, thread_id, in_reply_to, created_at, read_at, acked_at
  FROM messages
  WHERE project_key = $project_key AND to_persona = $persona_id AND read_at IS NULL
  ORDER BY created_at DESC
  LIMIT $limit
`);

const stmtMarkRead = db.prepare(`
  UPDATE messages SET read_at = datetime('now')
  WHERE project_key = $project_key AND to_persona = $persona_id AND read_at IS NULL
`);

export function fetchInbox(params: {
  project_key: string;
  persona_id: string;
  limit?: number;
  unread_only?: boolean;
}) {
  const limit = params.limit ?? 50;
  touchPersona(params.persona_id, params.project_key);

  const bindParams = { $project_key: params.project_key, $persona_id: params.persona_id, $limit: limit };
  const messages = params.unread_only
    ? stmtFetchInboxUnread.all(bindParams)
    : stmtFetchInbox.all(bindParams);

  stmtMarkRead.run({ $project_key: params.project_key, $persona_id: params.persona_id });

  return messages;
}

const stmtAckMessage = db.prepare(`
  UPDATE messages SET acked_at = datetime('now')
  WHERE message_id = $message_id AND project_key = $project_key AND to_persona = $persona_id
`);

export function ackMessage(params: {
  project_key: string;
  persona_id: string;
  message_id: string;
}) {
  const result = stmtAckMessage.run({
    $message_id: params.message_id,
    $project_key: params.project_key,
    $persona_id: params.persona_id,
  });
  return { ok: true, changed: result.changes > 0 };
}

const stmtAckAll = db.prepare(`
  UPDATE messages SET acked_at = datetime('now')
  WHERE project_key = $project_key AND to_persona = $persona_id AND acked_at IS NULL
`);

export function ackAll(params: { project_key: string; persona_id: string }) {
  const result = stmtAckAll.run({ $project_key: params.project_key, $persona_id: params.persona_id });
  return { ok: true, acked: result.changes };
}

const stmtUnreadCount = db.prepare(`
  SELECT COUNT(*) as count FROM messages
  WHERE project_key = $project_key AND to_persona = $persona_id AND read_at IS NULL
`);

export function getUnreadCount(params: {
  project_key: string;
  persona_id: string;
}) {
  touchPersona(params.persona_id, params.project_key);
  const row = stmtUnreadCount.get({ $project_key: params.project_key, $persona_id: params.persona_id }) as {
    count: number;
  };
  return { unread: row.count };
}

const stmtFetchThread = db.prepare(`
  SELECT message_id, from_persona, to_persona, subject, body, thread_id, in_reply_to, created_at, read_at
  FROM messages
  WHERE project_key = $project_key AND thread_id = $thread_id
  ORDER BY created_at ASC
`);

export function fetchThread(params: {
  project_key: string;
  thread_id: string;
}) {
  return stmtFetchThread.all({ $project_key: params.project_key, $thread_id: params.thread_id });
}

export function close() {
  db.close();
}
