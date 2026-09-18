-- First-phase MySQL schema for the conversation foundation.
-- This file is declarative only; it is not executed by BossHunter yet.
-- Do not run it against production without a separately approved migration plan.

CREATE TABLE sys_users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(320) NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_sys_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE job_companies (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    platform VARCHAR(32) NOT NULL,
    external_company_id VARCHAR(255) NULL,
    name VARCHAR(255) NOT NULL,
    homepage_url TEXT NULL,
    profile_url TEXT NULL,
    industry VARCHAR(255) NULL,
    company_size VARCHAR(128) NULL,
    location VARCHAR(255) NULL,
    raw_json JSON NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_job_company_external (platform, external_company_id),
    KEY idx_job_company_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE job_jobs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    platform VARCHAR(32) NOT NULL,
    external_job_id VARCHAR(255) NOT NULL,
    company_id BIGINT UNSIGNED NULL,
    title VARCHAR(255) NOT NULL,
    city VARCHAR(128) NULL,
    salary VARCHAR(128) NULL,
    experience VARCHAR(128) NULL,
    education VARCHAR(128) NULL,
    recruitment_type VARCHAR(64) NULL,
    jd_text MEDIUMTEXT NULL,
    url TEXT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'pending',
    score SMALLINT NULL,
    score_reason TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    last_seen_at DATETIME(6) NULL,
    UNIQUE KEY uq_job_external (platform, external_job_id),
    KEY idx_job_user_status (user_id, status, updated_at),
    CONSTRAINT fk_job_user FOREIGN KEY (user_id) REFERENCES sys_users(id),
    CONSTRAINT fk_job_company FOREIGN KEY (company_id) REFERENCES job_companies(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE know_documents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    document_type VARCHAR(32) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    storage_path TEXT NOT NULL,
    mime_type VARCHAR(128) NULL,
    file_size BIGINT UNSIGNED NULL,
    sha256 CHAR(64) NOT NULL,
    parse_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    visibility VARCHAR(32) NOT NULL DEFAULT 'private',
    source_kind VARCHAR(32) NOT NULL DEFAULT 'user_upload',
    version INT UNSIGNED NOT NULL DEFAULT 1,
    error_message TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_know_document_hash (user_id, sha256),
    KEY idx_know_document_status (user_id, parse_status),
    CONSTRAINT fk_know_document_user FOREIGN KEY (user_id) REFERENCES sys_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE know_chunks (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    document_id BIGINT UNSIGNED NOT NULL,
    section_title VARCHAR(255) NULL,
    chunk_index INT UNSIGNED NOT NULL,
    content MEDIUMTEXT NOT NULL,
    normalized_content MEDIUMTEXT NULL,
    token_count INT UNSIGNED NULL,
    embedding_json JSON NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_know_chunk_order (document_id, chunk_index),
    CONSTRAINT fk_know_chunk_document FOREIGN KEY (document_id) REFERENCES know_documents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE know_facts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    project_name VARCHAR(255) NULL,
    document_id BIGINT UNSIGNED NULL,
    fact_type VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content MEDIUMTEXT NOT NULL,
    technologies_json JSON NULL,
    responsibility TEXT NULL,
    problem TEXT NULL,
    solution TEXT NULL,
    result TEXT NULL,
    evidence_level VARCHAR(32) NOT NULL DEFAULT 'document_extracted',
    fact_status VARCHAR(32) NOT NULL DEFAULT 'needs_confirmation',
    public_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    source_locator VARCHAR(255) NULL,
    confirmed_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_know_fact_retrieval (user_id, fact_status, public_allowed),
    CONSTRAINT fk_know_fact_user FOREIGN KEY (user_id) REFERENCES sys_users(id),
    CONSTRAINT fk_know_fact_document FOREIGN KEY (document_id) REFERENCES know_documents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE conv_conversations (
    id CHAR(36) NOT NULL PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    platform VARCHAR(32) NOT NULL,
    external_conversation_id VARCHAR(255) NULL,
    hr_external_id VARCHAR(255) NULL,
    hr_name VARCHAR(255) NOT NULL DEFAULT '',
    hr_title VARCHAR(255) NULL,
    hr_avatar_url TEXT NULL,
    company_id BIGINT UNSIGNED NULL,
    job_id BIGINT UNSIGNED NULL,
    hr_profile_url TEXT NULL,
    company_url TEXT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'new',
    pause_reason VARCHAR(255) NULL,
    interest_score SMALLINT NULL,
    last_message_at DATETIME(6) NULL,
    last_sync_at DATETIME(6) NULL,
    sync_cursor VARCHAR(512) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_conv_external (user_id, platform, external_conversation_id),
    KEY idx_conv_status (user_id, status, updated_at),
    CONSTRAINT fk_conv_user FOREIGN KEY (user_id) REFERENCES sys_users(id),
    CONSTRAINT fk_conv_company FOREIGN KEY (company_id) REFERENCES job_companies(id),
    CONSTRAINT fk_conv_job FOREIGN KEY (job_id) REFERENCES job_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE conv_messages (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    conversation_id CHAR(36) NOT NULL,
    platform_message_id VARCHAR(255) NULL,
    sender_type VARCHAR(16) NOT NULL,
    content MEDIUMTEXT NOT NULL,
    message_time DATETIME(6) NULL,
    content_hash CHAR(64) NOT NULL,
    source_url TEXT NULL,
    raw_payload_json JSON NULL,
    is_ai_generated BOOLEAN NOT NULL DEFAULT FALSE,
    is_sent BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_conv_message_external (conversation_id, platform_message_id),
    UNIQUE KEY uq_conv_message_fallback (conversation_id, sender_type, message_time, content_hash),
    KEY idx_conv_message_time (conversation_id, message_time, id),
    CONSTRAINT fk_conv_message_conversation FOREIGN KEY (conversation_id) REFERENCES conv_conversations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE conv_sync_cursors (
    conversation_id CHAR(36) NOT NULL PRIMARY KEY,
    cursor_value VARCHAR(512) NULL,
    last_synced_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_conv_cursor_conversation FOREIGN KEY (conversation_id) REFERENCES conv_conversations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE notification_outbox (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    conversation_id CHAR(36) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    recipient VARCHAR(320) NOT NULL,
    subject VARCHAR(512) NOT NULL,
    body MEDIUMTEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    last_error TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    sent_at DATETIME(6) NULL,
    UNIQUE KEY uq_notification_identity (conversation_id, kind, subject),
    KEY idx_notification_status (status, created_at),
    CONSTRAINT fk_notification_conversation FOREIGN KEY (conversation_id) REFERENCES conv_conversations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE conv_scheduler_state (
    id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
    running_conversation_id CHAR(36) NULL,
    lease_until DATETIME(6) NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_scheduler_conversation FOREIGN KEY (running_conversation_id) REFERENCES conv_conversations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- SQLite remains the only runtime adapter in this repository. A MySQL adapter
-- must preserve the unique message/outbox keys and use a transaction plus
-- SELECT ... FOR UPDATE for scheduler claims before production migration.
