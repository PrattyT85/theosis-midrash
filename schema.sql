--
-- PostgreSQL database dump
--

\restrict e6UavTzbBxPuedEqWDqypSwrLrsELJ1EyUdujOMId638M8qYLMvcHD88h03HU9j

-- Dumped from database version 16.14 (Ubuntu 16.14-1.pgdg24.04+1)
-- Dumped by pg_dump version 16.14 (Ubuntu 16.14-1.pgdg24.04+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'SQL_ASCII';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: editions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.editions (
    id bigint NOT NULL,
    work_id bigint NOT NULL,
    language text NOT NULL,
    version_title text NOT NULL,
    version_source text,
    license text,
    is_source boolean,
    is_primary boolean,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: editions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.editions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: editions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.editions_id_seq OWNED BY public.editions.id;


--
-- Name: ingestion_manifest; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ingestion_manifest (
    id bigint NOT NULL,
    work_title text NOT NULL,
    language text NOT NULL,
    version_title text NOT NULL,
    source_url text NOT NULL,
    export_generated_at timestamp with time zone,
    segment_count integer DEFAULT 0 NOT NULL,
    imported_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ingestion_manifest_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ingestion_manifest_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ingestion_manifest_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ingestion_manifest_id_seq OWNED BY public.ingestion_manifest.id;


--
-- Name: segments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.segments (
    id bigint NOT NULL,
    work_id bigint NOT NULL,
    edition_id bigint NOT NULL,
    sefaria_ref text NOT NULL,
    he_ref text,
    section_path text[] DEFAULT '{}'::text[] NOT NULL,
    segment_number integer,
    text text NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, text)) STORED
);


--
-- Name: segments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.segments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: segments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.segments_id_seq OWNED BY public.segments.id;


--
-- Name: source_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_links (
    id bigint NOT NULL,
    source_ref text NOT NULL,
    target_ref text NOT NULL,
    link_type text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: source_links_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.source_links_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.source_links_id_seq OWNED BY public.source_links.id;


--
-- Name: works; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.works (
    id bigint NOT NULL,
    sefaria_title text NOT NULL,
    hebrew_title text,
    categories text[] DEFAULT '{}'::text[] NOT NULL,
    corpus text,
    description text,
    source_url text,
    discovered_at timestamp with time zone DEFAULT now() NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: works_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.works_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: works_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.works_id_seq OWNED BY public.works.id;


--
-- Name: editions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.editions ALTER COLUMN id SET DEFAULT nextval('public.editions_id_seq'::regclass);


--
-- Name: ingestion_manifest id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_manifest ALTER COLUMN id SET DEFAULT nextval('public.ingestion_manifest_id_seq'::regclass);


--
-- Name: segments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.segments ALTER COLUMN id SET DEFAULT nextval('public.segments_id_seq'::regclass);


--
-- Name: source_links id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_links ALTER COLUMN id SET DEFAULT nextval('public.source_links_id_seq'::regclass);


--
-- Name: works id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.works ALTER COLUMN id SET DEFAULT nextval('public.works_id_seq'::regclass);


--
-- Name: editions editions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.editions
    ADD CONSTRAINT editions_pkey PRIMARY KEY (id);


--
-- Name: editions editions_work_id_language_version_title_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.editions
    ADD CONSTRAINT editions_work_id_language_version_title_key UNIQUE (work_id, language, version_title);


--
-- Name: ingestion_manifest ingestion_manifest_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_manifest
    ADD CONSTRAINT ingestion_manifest_pkey PRIMARY KEY (id);


--
-- Name: ingestion_manifest ingestion_manifest_work_title_language_version_title_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_manifest
    ADD CONSTRAINT ingestion_manifest_work_title_language_version_title_key UNIQUE (work_title, language, version_title);


--
-- Name: segments segments_edition_id_sefaria_ref_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.segments
    ADD CONSTRAINT segments_edition_id_sefaria_ref_key UNIQUE (edition_id, sefaria_ref);


--
-- Name: segments segments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.segments
    ADD CONSTRAINT segments_pkey PRIMARY KEY (id);


--
-- Name: source_links source_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_links
    ADD CONSTRAINT source_links_pkey PRIMARY KEY (id);


--
-- Name: works works_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.works
    ADD CONSTRAINT works_pkey PRIMARY KEY (id);


--
-- Name: works works_sefaria_title_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.works
    ADD CONSTRAINT works_sefaria_title_key UNIQUE (sefaria_title);


--
-- Name: segments_search_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX segments_search_idx ON public.segments USING gin (search_vector);


--
-- Name: segments_work_ref_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX segments_work_ref_idx ON public.segments USING btree (work_id, sefaria_ref);


--
-- Name: source_links_dedupe_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX source_links_dedupe_idx ON public.source_links USING btree (source_ref, target_ref, link_type);


--
-- Name: source_links_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX source_links_lookup_idx ON public.source_links USING btree (source_ref, target_ref);


--
-- Name: editions editions_work_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.editions
    ADD CONSTRAINT editions_work_id_fkey FOREIGN KEY (work_id) REFERENCES public.works(id) ON DELETE CASCADE;


--
-- Name: segments segments_edition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.segments
    ADD CONSTRAINT segments_edition_id_fkey FOREIGN KEY (edition_id) REFERENCES public.editions(id) ON DELETE CASCADE;


--
-- Name: segments segments_work_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.segments
    ADD CONSTRAINT segments_work_id_fkey FOREIGN KEY (work_id) REFERENCES public.works(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict e6UavTzbBxPuedEqWDqypSwrLrsELJ1EyUdujOMId638M8qYLMvcHD88h03HU9j

