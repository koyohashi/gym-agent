-- Gym Agent schema. Run in the Supabase SQL editor.
-- The app connects with the service-role key (bypasses RLS). RLS is on with no
-- policies, so the anon key can read and write nothing.

create table sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  label text
);

-- at most one open session per user
create unique index one_active_session on sessions (user_id) where ended_at is null;

create table sets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  session_id uuid not null references sessions(id) on delete cascade,
  exercise_id text not null,
  weight numeric not null check (weight >= 0),
  reps integer not null check (reps > 0 and reps < 200),
  unit text not null default 'lbs' check (unit in ('lbs', 'kg')),
  note text,
  logged_at timestamptz not null default now()
);

create index sets_exercise_time on sets (user_id, exercise_id, logged_at desc);
create index sets_session_time on sets (session_id, logged_at desc);

create table user_exercises (
  id text primary key,
  user_id uuid not null,
  name text not null,
  aliases text[] not null default '{}',
  weight_type text not null check (weight_type in ('barbell', 'dumbbell', 'machine', 'cable', 'bodyweight')),
  muscle_group text
);

alter table sessions enable row level security;
alter table sets enable row level security;
alter table user_exercises enable row level security;
