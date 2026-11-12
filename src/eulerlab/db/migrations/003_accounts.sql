-- 003: accounts, workspaces, memberships, sessions and API tokens (ADR-168).
--
-- Who may act in which workspace, and how they prove it. Passwords and tokens
-- are stored as hashes only: a stolen copy of this table logs nobody in.
-- These tables are not append-only; a session ends and a token is revoked by
-- setting a time, never by deleting the row, so who held access stays known.

CREATE TABLE IF NOT EXISTS users (
    id            text        PRIMARY KEY,
    email         text        NOT NULL UNIQUE,
    name          text        NOT NULL DEFAULT '',
    password_hash text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    disabled_at   timestamptz
);

CREATE TABLE IF NOT EXISTS workspaces (
    id         text        PRIMARY KEY,
    name       text        NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO workspaces (id, name) VALUES ('default', 'Default') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS memberships (
    user_id      text        NOT NULL REFERENCES users (id),
    workspace_id text        NOT NULL REFERENCES workspaces (id),
    role         text        NOT NULL CHECK (role IN ('owner', 'researcher', 'viewer')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash text        PRIMARY KEY,
    user_id    text        NOT NULL REFERENCES users (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    ended_at   timestamptz
);

CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash   text        PRIMARY KEY,
    user_id      text        NOT NULL REFERENCES users (id),
    workspace_id text        NOT NULL REFERENCES workspaces (id),
    name         text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    revoked_at   timestamptz
);
