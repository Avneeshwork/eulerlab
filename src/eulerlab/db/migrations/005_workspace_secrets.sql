-- 005: each workspace's own keys, encrypted (ADR-170).
--
-- `ciphertext` is the value sealed with the server's EULERLAB_SECRET_KEY
-- (Fernet: AES-128-CBC with an HMAC). The key is never in this database, so a
-- copy of the table, or of its nightly export, opens nothing. A value is
-- replaced by a new row version, never read back out through any API.

CREATE TABLE IF NOT EXISTS workspace_secrets (
    workspace_id text        NOT NULL REFERENCES workspaces (id),
    name         text        NOT NULL CHECK (name ~ '^[A-Z][A-Z0-9_]{2,63}$'),
    ciphertext   text        NOT NULL,
    set_by       text        NOT NULL,
    set_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, name)
);
