-- 002: stream generations (ADR-166).
--
-- Some streams are reset: a paper book run with --reset, and the attribution
-- run, start from an empty order journal, and on files that meant deleting
-- `orders.jsonl`. An append-only table cannot delete, so a reset starts a new
-- generation instead. Generation 1 is the stream as named (`oms/paper/orders.jsonl`),
-- and is implicit: it has no row here. Generation n > 1 lives in append_log
-- under `<stream>@n`. The current generation is the highest number here.
--
-- Nothing is lost by a reset: every earlier generation is still in append_log,
-- and this table records when and why each new one began. It is append-only
-- like append_log, and a generation must be the next number.

CREATE TABLE IF NOT EXISTS stream_generation (
    workspace_id text        NOT NULL DEFAULT 'default',
    stream       text        NOT NULL,
    generation   integer     NOT NULL CHECK (generation >= 2),
    reason       text        NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, stream, generation)
);

CREATE OR REPLACE FUNCTION stream_generation_next() RETURNS trigger AS $$
DECLARE
    expected integer;
BEGIN
    SELECT coalesce(max(generation), 1) + 1 INTO expected
      FROM stream_generation
     WHERE workspace_id = NEW.workspace_id AND stream = NEW.stream;
    IF NEW.generation <> expected THEN
        RAISE EXCEPTION 'stream_generation %: generation % is not the next (%)',
            NEW.stream, NEW.generation, expected;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS stream_generation_no_update ON stream_generation;
CREATE TRIGGER stream_generation_no_update
    BEFORE UPDATE OR DELETE ON stream_generation
    FOR EACH ROW EXECUTE FUNCTION append_log_refuse_change();

DROP TRIGGER IF EXISTS stream_generation_no_truncate ON stream_generation;
CREATE TRIGGER stream_generation_no_truncate
    BEFORE TRUNCATE ON stream_generation
    FOR EACH STATEMENT EXECUTE FUNCTION append_log_refuse_change();

DROP TRIGGER IF EXISTS stream_generation_contiguous ON stream_generation;
CREATE TRIGGER stream_generation_contiguous
    BEFORE INSERT ON stream_generation
    FOR EACH ROW EXECUTE FUNCTION stream_generation_next();
