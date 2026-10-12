-- ============================================================
-- Migration 003: performance indexes for hot per-request queries.
-- Additive, idempotent. Target: ai-semantic-search branch.
-- ============================================================

-- The middleware runs an unread-message COUNT on every page request, joining
-- chat_messages -> chat_rooms and filtering on is_read / room membership.
CREATE INDEX IF NOT EXISTS idx_chat_messages_room_unread
    ON chat_messages (room_id, is_read);
CREATE INDEX IF NOT EXISTS idx_chat_rooms_user  ON chat_rooms (user_id);
CREATE INDEX IF NOT EXISTS idx_chat_rooms_agent ON chat_rooms (agent_id);

-- Reviews are loaded on every property-detail page.
CREATE INDEX IF NOT EXISTS idx_reviews_property ON reviews (property_id);
