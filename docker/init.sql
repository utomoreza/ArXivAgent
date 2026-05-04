-- Creates application and test databases, enables pgvector in both.
-- Executed once by the postgres container on first startup.

CREATE DATABASE arxivagent;
CREATE DATABASE arxiv_test;

\connect arxivagent
CREATE EXTENSION IF NOT EXISTS vector;

\connect arxiv_test
CREATE EXTENSION IF NOT EXISTS vector;
