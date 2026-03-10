import { Database } from "bun:sqlite";
import path from "path";

const DB_PATH = process.env.COWORK_MAIL_DB || path.join(process.cwd(), "cowork-mail.db");

const db = new Database(DB_PATH, { create: true });

db.run("PRAGMA journal_mode = WAL");
db.run("PRAGMA foreign_keys = ON");

db.exec(`
  CREATE TABLE IF NOT EXISTS personas (
    persona_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    from_persona TEXT NOT NULL,
    to_persona TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    read_at TEXT,
    acked_at TEXT
  );

  CREATE INDEX IF NOT EXISTS idx_messages_inbox
    ON messages(to_persona, acked_at);
  CREATE INDEX IF NOT EXISTS idx_messages_unread
    ON messages(to_persona, read_at);
`);

// --- Personas ---

const stmtRegister = db.prepare(`
  INSERT INTO personas (persona_id, display_name)
  VALUES ($persona_id, $display_name)
  ON CONFLICT(persona_id) DO UPDATE SET
    display_name = $display_name,
    last_seen_at = datetime('now')
`);

const stmtListPersonas = db.prepare(`
  SELECT persona_id, display_name, registered_at, last_seen_at
  FROM personas ORDER BY persona_id
`);

const stmtTouch = db.prepare(`
  UPDATE personas SET last_seen_at = datetime('now') WHERE persona_id = $persona_id
`);

export function registerPersona(persona_id: string, display_name?: string) {
  stmtRegister.run({ $persona_id: persona_id, $display_name: display_name || persona_id });
  return { ok: true, persona_id };
}

export function listPersonas() {
  return stmtListPersonas.all();
}

function touch(persona_id: string) {
  stmtTouch.run({ $persona_id: persona_id });
}

// --- Messages ---

function genId(): string {
  return `msg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

const stmtInsert = db.prepare(`
  INSERT INTO messages (message_id, from_persona, to_persona, payload)
  VALUES ($message_id, $from_persona, $to_persona, $payload)
`);

export function sendMessage(from_persona: string, to: string[], payload: unknown) {
  const payloadStr = typeof payload === "string" ? payload : JSON.stringify(payload);
  const ids: string[] = [];
  const tx = db.transaction(() => {
    for (const recipient of to) {
      const id = genId();
      stmtInsert.run({
        $message_id: id,
        $from_persona: from_persona,
        $to_persona: recipient,
        $payload: payloadStr,
      });
      ids.push(id);
    }
    touch(from_persona);
  });
  tx();
  return { ok: true, message_ids: ids, recipients: to };
}

const stmtInbox = db.prepare(`
  SELECT message_id, from_persona, to_persona, payload, created_at, read_at, acked_at
  FROM messages WHERE to_persona = $persona_id AND acked_at IS NULL
  ORDER BY created_at DESC LIMIT $limit
`);

const stmtInboxUnread = db.prepare(`
  SELECT message_id, from_persona, to_persona, payload, created_at, read_at, acked_at
  FROM messages WHERE to_persona = $persona_id AND read_at IS NULL
  ORDER BY created_at DESC LIMIT $limit
`);

const stmtMarkRead = db.prepare(`
  UPDATE messages SET read_at = datetime('now')
  WHERE to_persona = $persona_id AND read_at IS NULL
`);

export function fetchInbox(persona_id: string, limit = 50, unread_only = false) {
  touch(persona_id);
  const rows = (unread_only ? stmtInboxUnread : stmtInbox).all({
    $persona_id: persona_id,
    $limit: limit,
  }) as { message_id: string; from_persona: string; to_persona: string; payload: string; created_at: string; read_at: string | null; acked_at: string | null }[];
  stmtMarkRead.run({ $persona_id: persona_id });
  return rows.map((r) => ({
    ...r,
    payload: tryParse(r.payload),
  }));
}

function tryParse(s: string): unknown {
  try { return JSON.parse(s); } catch { return s; }
}

const stmtAck = db.prepare(`
  UPDATE messages SET acked_at = datetime('now')
  WHERE message_id = $message_id AND to_persona = $persona_id
`);

export function ackMessage(persona_id: string, message_id: string) {
  const r = stmtAck.run({ $message_id: message_id, $persona_id: persona_id });
  return { ok: true, changed: r.changes > 0 };
}

const stmtAckAll = db.prepare(`
  UPDATE messages SET acked_at = datetime('now')
  WHERE to_persona = $persona_id AND acked_at IS NULL
`);

export function ackAll(persona_id: string) {
  const r = stmtAckAll.run({ $persona_id: persona_id });
  return { ok: true, acked: r.changes };
}

const stmtUnread = db.prepare(`
  SELECT COUNT(*) as count FROM messages
  WHERE to_persona = $persona_id AND read_at IS NULL
`);

const stmtLatest = db.prepare(`
  SELECT message_id FROM messages
  WHERE to_persona = $persona_id AND read_at IS NULL
  ORDER BY created_at DESC LIMIT 1
`);

export function getUnreadCount(persona_id: string) {
  touch(persona_id);
  const row = stmtUnread.get({ $persona_id: persona_id }) as { count: number };
  const latest = stmtLatest.get({ $persona_id: persona_id }) as { message_id: string } | null;
  return {
    unread: row.count,
    latest_message_id: latest?.message_id ?? "",
  };
}
