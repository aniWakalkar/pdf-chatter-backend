ALTER TABLE message_sources DROP CONSTRAINT IF EXISTS message_sources_message_id_fkey;

ALTER TABLE message_sources
    ADD CONSTRAINT message_sources_message_id_fkey
    FOREIGN KEY (message_id) REFERENCES messages(id)
    ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;
