-- 005_ai_chat_history.sql
-- Make the existing ai_chat_messages table usable for persisted AI-chat history.
--   - properties_json: the listing cards the assistant returned for a turn, so the
--     conversation (including results) can be replayed when the page is reopened.
--   - index on (user_id, created_at) for fast per-user history loads.

ALTER TABLE ai_chat_messages ADD COLUMN IF NOT EXISTS properties_json jsonb;

CREATE INDEX IF NOT EXISTS idx_ai_chat_user_time
    ON ai_chat_messages (user_id, created_at);
