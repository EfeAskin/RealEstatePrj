-- 006_ai_conversations.sql
-- Add ChatGPT-style conversation threads to the AI chat.
--   - ai_conversations: one row per chat thread (title + timestamps) per user.
--   - ai_chat_messages.conversation_id: which thread a message belongs to.
-- Existing thread-less messages are folded into one "Previous chat" per user.

CREATE TABLE IF NOT EXISTS ai_conversations (
    conversation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         integer NOT NULL,
    title           text,
    created_at      timestamptz DEFAULT now(),
    updated_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_conv_user_updated
    ON ai_conversations (user_id, updated_at DESC);

ALTER TABLE ai_chat_messages ADD COLUMN IF NOT EXISTS conversation_id uuid;

-- Backfill: group any pre-existing (thread-less) messages into one thread per user.
WITH new_convs AS (
    INSERT INTO ai_conversations (user_id, title, created_at, updated_at)
    SELECT user_id, 'Previous chat', MIN(created_at), MAX(created_at)
    FROM ai_chat_messages
    WHERE conversation_id IS NULL
    GROUP BY user_id
    RETURNING conversation_id, user_id
)
UPDATE ai_chat_messages m
SET conversation_id = nc.conversation_id
FROM new_convs nc
WHERE m.user_id = nc.user_id AND m.conversation_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_ai_chat_conv
    ON ai_chat_messages (conversation_id, created_at);
