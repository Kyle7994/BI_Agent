-- 002_retrieval_tables.sql

CREATE TABLE schema_chunks (
    id BIGSERIAL PRIMARY KEY,
    chunk_type VARCHAR(32) NOT NULL,
    source_name VARCHAR(128) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL,
    embedding VECTOR(768) 
);

CREATE TABLE sql_examples (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    sql_text TEXT NOT NULL,
    features JSONB NOT NULL,
    embedding VECTOR(768)
);