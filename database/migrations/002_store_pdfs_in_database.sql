CREATE TABLE IF NOT EXISTS document_files (
    document_id UUID PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    content BYTEA NOT NULL
);

UPDATE documents
SET status = 'failed', chunk_count = 0, error_message = 'The original file is missing. Please delete and upload it again.'
WHERE id NOT IN (SELECT document_id FROM document_files);

ALTER TABLE documents DROP COLUMN IF EXISTS storage_key;
