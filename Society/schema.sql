-- Signal Society V2 tables. Run once in the Supabase SQL editor.

create table if not exists soc_agents (
  id text primary key,
  "name" text,
  "status" text,
  "generation" integer,
  "parents" text,
  "voice" text,
  "backstory" text,
  "genome" text,
  "energy" double precision,
  "profession" text,
  "domain_xp" text,
  "born_tick" integer,
  "born_at" text,
  "retired_at" text,
  "fitness" double precision,
  "color" text
);
alter table soc_agents disable row level security;

create table if not exists soc_messages (
  id text primary key,
  "ts" text,
  "tick" integer,
  "sender" text,
  "recipient" text,
  "kind" text,
  "body" text,
  "read" integer,
  "meta" text
);
alter table soc_messages disable row level security;

create table if not exists soc_relationships (
  id text primary key,
  "pair" text,
  "a" text,
  "b" text,
  "affinity" double precision,
  "kind" text,
  "interactions" integer,
  "updated_at" text
);
alter table soc_relationships disable row level security;

create table if not exists soc_findings (
  id text primary key,
  "ts" text,
  "tick" integer,
  "agent" text,
  "kind" text,
  "domain" text,
  "title" text,
  "body" text,
  "sources" text,
  "confidence" double precision,
  "reviews" text,
  "review_avg" double precision,
  "review_count" integer,
  "reactions" text,
  "sil_score" double precision
);
alter table soc_findings disable row level security;

create table if not exists soc_memories (
  id text primary key,
  "ts" text,
  "agent" text,
  "text" text,
  "importance" integer
);
alter table soc_memories disable row level security;

create table if not exists soc_events (
  id text primary key,
  "ts" text,
  "tick" integer,
  "agent" text,
  "type" text,
  "text" text,
  "meta" text
);
alter table soc_events disable row level security;

create table if not exists soc_world (
  id text primary key,
  "value" text
);
alter table soc_world disable row level security;

create index if not exists i_ev_ts on soc_events(ts);
create index if not exists i_msg_rcpt on soc_messages(recipient, read);
create index if not exists i_find_agent on soc_findings(agent);
