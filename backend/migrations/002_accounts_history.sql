CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username VARCHAR(50) NOT NULL,
  username_key VARCHAR(50) NOT NULL UNIQUE,
  email VARCHAR(320) NOT NULL,
  email_key VARCHAR(320) NOT NULL UNIQUE,
  phone_number VARCHAR(32) NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_users_username_key ON users (username_key);
CREATE INDEX IF NOT EXISTS ix_users_email_key ON users (email_key);

CREATE TABLE IF NOT EXISTS auth_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash VARCHAR(64) NOT NULL UNIQUE,
  expires_at TIMESTAMP NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_auth_sessions_user_id ON auth_sessions (user_id);

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL UNIQUE REFERENCES workspaces(id) ON DELETE CASCADE,
  title VARCHAR(160) NOT NULL,
  preview VARCHAR(280) NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_conversations_owner_id ON conversations (owner_id);
CREATE INDEX IF NOT EXISTS ix_conversations_workspace_id ON conversations (workspace_id);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role VARCHAR(16) NOT NULL,
  content TEXT NOT NULL,
  result_reference TEXT,
  created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_conversation_messages_conversation_id
  ON conversation_messages (conversation_id);

CREATE TABLE IF NOT EXISTS conversation_shares (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  recipient_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  permission VARCHAR(16) NOT NULL DEFAULT 'VIEW',
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT uq_conversation_recipient UNIQUE (conversation_id, recipient_id),
  CONSTRAINT ck_conversation_share_permission CHECK (permission IN ('VIEW'))
);

CREATE INDEX IF NOT EXISTS ix_conversation_shares_conversation_id
  ON conversation_shares (conversation_id);
CREATE INDEX IF NOT EXISTS ix_conversation_shares_recipient_id
  ON conversation_shares (recipient_id);
