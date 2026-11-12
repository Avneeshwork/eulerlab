-- 001: the append-only log (ADR-165).
--
-- One table holds every stream that used to be a JSON-lines file written only
-- at its end: the trial ledger, each order journal, and next the agent log and
-- the kill-switch log. `stream` is the file's path under EULERLAB_DATA_DIR
-- (`derived/trial_ledger.jsonl`), so a row and the line it replaces name the
-- same thing. `body` is that line, byte for byte: the trial ledger's hash
-- covers the JSON text, and jsonb would reorder keys and refuse NaN.
--
-- Append-only is a property of the table, not a promise: UPDATE, DELETE and
-- TRUNCATE raise, and an INSERT whose seq is not the stream's next number
-- raises. The file version could only detect an edit (the hash chain); this
-- refuses it.

CREATE TABLE IF NOT EXISTS append_log (
    workspace_id   text        NOT NULL DEFAULT 'default',
    kind           text        NOT NULL,
    stream         text        NOT NULL,
    seq            integer     NOT NULL CHECK (seq >= 1),
    body           text        NOT NULL,
    event_time     timestamptz NOT NULL,
    knowledge_time timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, stream, seq)
);

CREATE INDEX IF NOT EXISTS append_log_kind ON append_log (workspace_id, kind);

CREATE OR REPLACE FUNCTION append_log_refuse_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'append_log is append-only: % refused', TG_OP;
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION append_log_next_seq() RETURNS trigger AS $$
DECLARE
    expected integer;
BEGIN
    SELECT coalesce(max(seq), 0) + 1 INTO expected
      FROM append_log
     WHERE workspace_id = NEW.workspace_id AND stream = NEW.stream;
    IF NEW.seq <> expected THEN
        RAISE EXCEPTION 'append_log %: seq % is not the next (%)', NEW.stream, NEW.seq, expected;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS append_log_no_update ON append_log;
CREATE TRIGGER append_log_no_update
    BEFORE UPDATE OR DELETE ON append_log
    FOR EACH ROW EXECUTE FUNCTION append_log_refuse_change();

DROP TRIGGER IF EXISTS append_log_no_truncate ON append_log;
CREATE TRIGGER append_log_no_truncate
    BEFORE TRUNCATE ON append_log
    FOR EACH STATEMENT EXECUTE FUNCTION append_log_refuse_change();

DROP TRIGGER IF EXISTS append_log_contiguous ON append_log;
CREATE TRIGGER append_log_contiguous
    BEFORE INSERT ON append_log
    FOR EACH ROW EXECUTE FUNCTION append_log_next_seq();
