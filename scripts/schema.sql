-- ============================================================
-- CypInvEst — full database schema (schema only, no data)
--
-- Use this to set up a BRAND-NEW, EMPTY PostgreSQL database:
--     python scripts/run_migration.py scripts/schema.sql
--     python scripts/run_migration.py scripts/seed_features.sql
--
-- It is a snapshot of the live schema and already includes everything
-- from scripts/migrations/001–006, so you do NOT need to run those on a
-- fresh database. Existing databases should apply the numbered
-- migrations instead.
--
-- Requires PostgreSQL 13+ with the pgvector extension available
-- (Neon has it built in).
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS vector;

DO $$ BEGIN
    CREATE TYPE ticket_status_enum AS ENUM ('Waiting', 'Active', 'Success', 'Failed', 'Spam');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE ticket_type_enum AS ENUM ('Support', 'Bugs', 'Complaints', 'Desire', 'Others');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE OR REPLACE FUNCTION public.set_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.update_modified_column()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$;

CREATE SEQUENCE IF NOT EXISTS appointments_id_seq;
CREATE SEQUENCE IF NOT EXISTS chat_messages_id_seq;
CREATE SEQUENCE IF NOT EXISTS chat_rooms_id_seq;
CREATE SEQUENCE IF NOT EXISTS features_id_seq;
CREATE SEQUENCE IF NOT EXISTS properties_id_seq;
CREATE SEQUENCE IF NOT EXISTS property_images_id_seq;
CREATE SEQUENCE IF NOT EXISTS property_price_history_id_seq;
CREATE SEQUENCE IF NOT EXISTS reviews_id_seq;
CREATE SEQUENCE IF NOT EXISTS search_logs_id_seq;
CREATE SEQUENCE IF NOT EXISTS ticket_messages_id_seq;
CREATE SEQUENCE IF NOT EXISTS tickets_id_seq;
CREATE SEQUENCE IF NOT EXISTS user_events_id_seq;
CREATE SEQUENCE IF NOT EXISTS user_favorites_id_seq;
CREATE SEQUENCE IF NOT EXISTS users_id_seq;

CREATE TABLE IF NOT EXISTS agents (
    id integer NOT NULL,
    agency_name character varying(150),
    phone_number character varying(20),
    agent_image character varying(255) DEFAULT 'default_agent.png'::character varying,
    joined_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    is_verified boolean DEFAULT false,
    bio text
);

CREATE TABLE IF NOT EXISTS ai_chat_messages (
    message_id uuid DEFAULT gen_random_uuid() NOT NULL,
    role character varying NOT NULL,
    message text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    user_id integer NOT NULL,
    properties_json jsonb,
    conversation_id uuid
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    conversation_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id integer NOT NULL,
    title text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS appointments (
    id integer DEFAULT nextval('appointments_id_seq'::regclass) NOT NULL,
    client_id integer,
    expert_id integer,
    title character varying(255),
    appointment_date timestamp with time zone,
    duration_minutes integer DEFAULT 45,
    status character varying(50) DEFAULT 'pending'::character varying,
    meeting_link character varying(500),
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id integer DEFAULT nextval('chat_messages_id_seq'::regclass) NOT NULL,
    room_id integer,
    sender_id integer,
    is_from_ai boolean DEFAULT false,
    message_text text NOT NULL,
    is_read boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_rooms (
    id integer DEFAULT nextval('chat_rooms_id_seq'::regclass) NOT NULL,
    property_id integer,
    user_id integer,
    agent_id integer,
    is_ai_chat boolean DEFAULT false,
    openai_thread_id character varying(255) DEFAULT NULL::character varying,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS features (
    id integer DEFAULT nextval('features_id_seq'::regclass) NOT NULL,
    name character varying(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS properties (
    id integer DEFAULT nextval('properties_id_seq'::regclass) NOT NULL,
    name character varying(255) NOT NULL,
    location character varying(255) NOT NULL,
    monthly_price numeric(15,2),
    image text,
    listing_type character varying(20),
    guests integer DEFAULT 0,
    beds integer DEFAULT 0,
    baths integer DEFAULT 0,
    description text,
    owner_email character varying(255),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    country character varying(100) DEFAULT 'North Cyprus'::character varying,
    city character varying(100),
    district character varying(100),
    net_m2 integer,
    room_count character varying(50),
    building_age character varying(50),
    heating character varying(100),
    furnished character varying(20),
    currency character varying(10) DEFAULT 'TL'::character varying,
    price_normalized integer,
    source_url text,
    status character varying(20) DEFAULT 'active'::character varying,
    avg_rating numeric DEFAULT 5.0,
    gross_m2 integer,
    open_m2 integer,
    currency_code character varying(10),
    dues integer,
    is_site character varying(10),
    site_name character varying(255),
    is_credit character varying(10),
    deed_status character varying(100),
    is_trade character varying(10),
    property_type text,
    agent_id integer,
    embedding vector(1536),
    embedding_text text,
    embedding_synced_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now(),
    embedding_status character varying(16) DEFAULT 'pending'::character varying NOT NULL
);

CREATE TABLE IF NOT EXISTS property_features (
    property_id integer NOT NULL,
    feature_id integer NOT NULL
);

CREATE TABLE IF NOT EXISTS property_images (
    id integer DEFAULT nextval('property_images_id_seq'::regclass) NOT NULL,
    property_id integer NOT NULL,
    image_url text NOT NULL,
    is_main boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS property_price_history (
    id integer DEFAULT nextval('property_price_history_id_seq'::regclass) NOT NULL,
    property_id integer,
    old_price integer,
    new_price integer,
    changed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reviews (
    id integer DEFAULT nextval('reviews_id_seq'::regclass) NOT NULL,
    property_id integer,
    user_name character varying(100),
    comment text,
    rating_main numeric,
    rating_cleanliness integer,
    rating_accuracy integer,
    rating_communication integer,
    rating_location integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS search_logs (
    id integer DEFAULT nextval('search_logs_id_seq'::regclass) NOT NULL,
    user_id integer,
    query_text text,
    filters_json jsonb,
    result_count integer,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ticket_messages (
    id integer DEFAULT nextval('ticket_messages_id_seq'::regclass) NOT NULL,
    ticket_id integer NOT NULL,
    sender_id integer NOT NULL,
    message_text text NOT NULL,
    sent_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tickets (
    id integer DEFAULT nextval('tickets_id_seq'::regclass) NOT NULL,
    sender_id integer NOT NULL,
    receiver_id integer,
    subject character varying(255) NOT NULL,
    ticket_type ticket_type_enum NOT NULL,
    ticket_status ticket_status_enum DEFAULT 'Waiting'::ticket_status_enum NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_events (
    id integer DEFAULT nextval('user_events_id_seq'::regclass) NOT NULL,
    user_id integer,
    property_id integer,
    event_type character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    session_id character varying
);

CREATE TABLE IF NOT EXISTS user_favorites (
    id integer DEFAULT nextval('user_favorites_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    property_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id integer NOT NULL,
    preferred_city character varying,
    preferred_district character varying,
    min_price integer,
    max_price integer,
    min_beds integer,
    max_beds integer,
    property_type text,
    furnished character varying,
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id integer DEFAULT nextval('users_id_seq'::regclass) NOT NULL,
    email character varying(255) NOT NULL,
    password text NOT NULL,
    first_name character varying(100) NOT NULL,
    last_name character varying(100) NOT NULL,
    phone character varying(20),
    gender character varying(20),
    role character varying(20) DEFAULT 'user'::character varying NOT NULL,
    iban character varying(50),
    id_no character varying(20),
    company_name character varying(255),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    payment_info_completed boolean DEFAULT false,
    profile_image character varying(255) DEFAULT 'default_user.png'::character varying,
    taste_embedding vector(1536),
    taste_updated_at timestamp with time zone
);

ALTER TABLE agents ADD CONSTRAINT agents_pkey PRIMARY KEY (id);
ALTER TABLE ai_chat_messages ADD CONSTRAINT ai_chat_messages_pkey PRIMARY KEY (message_id);
ALTER TABLE ai_chat_messages ADD CONSTRAINT role_check CHECK (((role)::text = ANY ((ARRAY['user'::character varying, 'assistant'::character varying, 'system'::character varying])::text[])));
ALTER TABLE ai_conversations ADD CONSTRAINT ai_conversations_pkey PRIMARY KEY (conversation_id);
ALTER TABLE appointments ADD CONSTRAINT appointments_pkey PRIMARY KEY (id);
ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_pkey PRIMARY KEY (id);
ALTER TABLE chat_rooms ADD CONSTRAINT unique_property_user_agent UNIQUE (property_id, user_id, agent_id);
ALTER TABLE chat_rooms ADD CONSTRAINT chat_rooms_pkey PRIMARY KEY (id);
ALTER TABLE features ADD CONSTRAINT features_name_key UNIQUE (name);
ALTER TABLE features ADD CONSTRAINT features_pkey PRIMARY KEY (id);
ALTER TABLE properties ADD CONSTRAINT unique_source_url UNIQUE (source_url);
ALTER TABLE properties ADD CONSTRAINT properties_pkey PRIMARY KEY (id);
ALTER TABLE property_features ADD CONSTRAINT property_features_pkey PRIMARY KEY (property_id, feature_id);
ALTER TABLE property_images ADD CONSTRAINT property_images_pkey PRIMARY KEY (id);
ALTER TABLE property_price_history ADD CONSTRAINT property_price_history_pkey PRIMARY KEY (id);
ALTER TABLE reviews ADD CONSTRAINT reviews_pkey PRIMARY KEY (id);
ALTER TABLE search_logs ADD CONSTRAINT search_logs_pkey PRIMARY KEY (id);
ALTER TABLE ticket_messages ADD CONSTRAINT ticket_messages_pkey PRIMARY KEY (id);
ALTER TABLE tickets ADD CONSTRAINT tickets_pkey PRIMARY KEY (id);
ALTER TABLE user_events ADD CONSTRAINT user_events_pkey PRIMARY KEY (id);
ALTER TABLE user_favorites ADD CONSTRAINT unique_user_property_favorite UNIQUE (user_id, property_id);
ALTER TABLE user_favorites ADD CONSTRAINT user_favorites_pkey PRIMARY KEY (id);
ALTER TABLE user_preferences ADD CONSTRAINT user_preferences_pkey PRIMARY KEY (user_id);
ALTER TABLE users ADD CONSTRAINT users_email_key UNIQUE (email);
ALTER TABLE users ADD CONSTRAINT users_pkey PRIMARY KEY (id);

ALTER TABLE agents ADD CONSTRAINT agents_id_fkey FOREIGN KEY (id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE ai_chat_messages ADD CONSTRAINT fk_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON UPDATE SET NULL ON DELETE SET NULL;
ALTER TABLE appointments ADD CONSTRAINT appointments_client_id_fkey FOREIGN KEY (client_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE appointments ADD CONSTRAINT appointments_expert_id_fkey FOREIGN KEY (expert_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_room_id_fkey FOREIGN KEY (room_id) REFERENCES chat_rooms(id) ON DELETE CASCADE;
ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_sender_id_fkey FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE chat_rooms ADD CONSTRAINT chat_rooms_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE chat_rooms ADD CONSTRAINT chat_rooms_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE SET NULL;
ALTER TABLE chat_rooms ADD CONSTRAINT chat_rooms_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE properties ADD CONSTRAINT fk_properties_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL;
ALTER TABLE properties ADD CONSTRAINT properties_owner_email_fkey FOREIGN KEY (owner_email) REFERENCES users(email) ON DELETE SET NULL;
ALTER TABLE property_features ADD CONSTRAINT property_features_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES features(id) ON DELETE CASCADE;
ALTER TABLE property_features ADD CONSTRAINT property_features_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE;
ALTER TABLE property_images ADD CONSTRAINT fk_property FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE;
ALTER TABLE property_price_history ADD CONSTRAINT property_price_history_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE;
ALTER TABLE reviews ADD CONSTRAINT reviews_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE;
ALTER TABLE search_logs ADD CONSTRAINT search_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE ticket_messages ADD CONSTRAINT fk_messages_sender FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE ticket_messages ADD CONSTRAINT fk_messages_ticket FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE;
ALTER TABLE tickets ADD CONSTRAINT fk_tickets_receiver FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE tickets ADD CONSTRAINT fk_tickets_sender FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE user_events ADD CONSTRAINT user_events_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id);
ALTER TABLE user_events ADD CONSTRAINT user_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE user_favorites ADD CONSTRAINT fk_property FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE;
ALTER TABLE user_favorites ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE user_preferences ADD CONSTRAINT user_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

ALTER SEQUENCE appointments_id_seq OWNED BY appointments.id;
ALTER SEQUENCE chat_messages_id_seq OWNED BY chat_messages.id;
ALTER SEQUENCE chat_rooms_id_seq OWNED BY chat_rooms.id;
ALTER SEQUENCE features_id_seq OWNED BY features.id;
ALTER SEQUENCE properties_id_seq OWNED BY properties.id;
ALTER SEQUENCE property_images_id_seq OWNED BY property_images.id;
ALTER SEQUENCE property_price_history_id_seq OWNED BY property_price_history.id;
ALTER SEQUENCE reviews_id_seq OWNED BY reviews.id;
ALTER SEQUENCE search_logs_id_seq OWNED BY search_logs.id;
ALTER SEQUENCE ticket_messages_id_seq OWNED BY ticket_messages.id;
ALTER SEQUENCE tickets_id_seq OWNED BY tickets.id;
ALTER SEQUENCE user_events_id_seq OWNED BY user_events.id;
ALTER SEQUENCE user_favorites_id_seq OWNED BY user_favorites.id;
ALTER SEQUENCE users_id_seq OWNED BY users.id;

CREATE INDEX IF NOT EXISTS idx_ai_chat_conv ON public.ai_chat_messages USING btree (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_chat_user_time ON public.ai_chat_messages USING btree (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_conv_user_updated ON public.ai_conversations USING btree (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_room_unread ON public.chat_messages USING btree (room_id, is_read);
CREATE INDEX IF NOT EXISTS idx_chat_rooms_agent ON public.chat_rooms USING btree (agent_id);
CREATE INDEX IF NOT EXISTS idx_chat_rooms_user ON public.chat_rooms USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_properties_agent ON public.properties USING btree (agent_id);
CREATE INDEX IF NOT EXISTS idx_properties_status ON public.properties USING btree (status);
CREATE INDEX IF NOT EXISTS properties_embedding_hnsw ON public.properties USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64');
CREATE INDEX IF NOT EXISTS idx_property_features_feature ON public.property_features USING btree (feature_id);
CREATE INDEX IF NOT EXISTS idx_property_images_property_id ON public.property_images USING btree (property_id);
CREATE INDEX IF NOT EXISTS idx_reviews_property ON public.reviews USING btree (property_id);
CREATE INDEX IF NOT EXISTS idx_search_logs_created ON public.search_logs USING btree (created_at);
CREATE INDEX IF NOT EXISTS idx_search_logs_zero ON public.search_logs USING btree (result_count) WHERE (result_count = 0);
CREATE INDEX IF NOT EXISTS idx_user_events_property ON public.user_events USING btree (property_id);
CREATE INDEX IF NOT EXISTS idx_user_events_type ON public.user_events USING btree (event_type);
CREATE INDEX IF NOT EXISTS idx_user_events_user ON public.user_events USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_user_favorites_property ON public.user_favorites USING btree (property_id);

CREATE TRIGGER trg_properties_updated_at BEFORE UPDATE ON public.properties FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER update_tickets_modtime BEFORE UPDATE ON public.tickets FOR EACH ROW EXECUTE FUNCTION update_modified_column();
