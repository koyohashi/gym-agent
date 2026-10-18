-- Sample history for the local stack only (supabase db reset loads it; production never runs it).
-- Rows belong to the app's default owner id, so a local app run shows them. Tests use random ids.

insert into sessions (id, user_id, started_at, ended_at, label) values
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   now() - interval '7 days', now() - interval '7 days' + interval '70 minutes', 'push'),
  ('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001',
   now() - interval '5 days', now() - interval '5 days' + interval '60 minutes', 'legs'),
  ('10000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001',
   now() - interval '2 days', now() - interval '2 days' + interval '65 minutes', 'push');

insert into sets (user_id, session_id, exercise_id, weight, reps, unit, note, logged_at)
select '00000000-0000-0000-0000-000000000001', s.id, v.exercise_id, v.weight, v.reps, v.unit, v.note,
       s.started_at + v.minutes * interval '1 minute'
from (values
  ('10000000-0000-0000-0000-000000000001'::uuid, 'bench_press', 135, 8, 'lbs', null, 5),
  ('10000000-0000-0000-0000-000000000001'::uuid, 'bench_press', 155, 6, 'lbs', null, 10),
  ('10000000-0000-0000-0000-000000000001'::uuid, 'bench_press', 165, 5, 'lbs', 'felt heavy', 15),
  ('10000000-0000-0000-0000-000000000001'::uuid, 'dip', 0, 12, 'lbs', null, 30),
  ('10000000-0000-0000-0000-000000000002'::uuid, 'back_squat', 185, 8, 'lbs', null, 5),
  ('10000000-0000-0000-0000-000000000002'::uuid, 'back_squat', 225, 5, 'lbs', null, 12),
  ('10000000-0000-0000-0000-000000000002'::uuid, 'deadlift', 140, 3, 'kg', null, 30),
  ('10000000-0000-0000-0000-000000000003'::uuid, 'bench_press', 145, 8, 'lbs', null, 5),
  ('10000000-0000-0000-0000-000000000003'::uuid, 'bench_press', 170, 4, 'lbs', null, 12),
  ('10000000-0000-0000-0000-000000000003'::uuid, 'dip', 25, 8, 'lbs', null, 30)
) as v(session_id, exercise_id, weight, reps, unit, note, minutes)
join sessions s on s.id = v.session_id;
