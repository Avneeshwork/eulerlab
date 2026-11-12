-- 004: failed logins (T-4568) and each workspace's stricter gate rules (ADR-169).
--
-- login_failures: one row per wrong password, so a guesser is slowed down
-- across every server, not per process. Rows are counted over a short window
-- and are not secrets.
--
-- workspace_gate: a workspace owner's tightening of the platform gate. A
-- history, not a setting: every change is a new row and the newest one is in
-- force, so what bar a past verdict was held to can always be answered.

CREATE TABLE IF NOT EXISTS login_failures (
    email   text        NOT NULL,
    address text        NOT NULL DEFAULT '',
    at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS login_failures_email ON login_failures (email, at);
CREATE INDEX IF NOT EXISTS login_failures_address ON login_failures (address, at);

CREATE TABLE IF NOT EXISTS workspace_gate (
    workspace_id text        NOT NULL REFERENCES workspaces (id),
    version      integer     NOT NULL CHECK (version >= 1),
    rules        text        NOT NULL,
    set_by       text        NOT NULL,
    set_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, version)
);

DROP TRIGGER IF EXISTS workspace_gate_no_update ON workspace_gate;
CREATE TRIGGER workspace_gate_no_update
    BEFORE UPDATE OR DELETE ON workspace_gate
    FOR EACH ROW EXECUTE FUNCTION append_log_refuse_change();
