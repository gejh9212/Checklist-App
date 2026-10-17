-- Apply to a new Supabase project. All account writes go through revision-checked RPCs.
begin;
create schema if not exists private;
revoke all on schema private from public;

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  timezone text not null default 'Asia/Seoul',
  settings jsonb not null default '{"light":false,"completed_bottom":false,"confirm":true}',
  revision bigint not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table public.checklists (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(user_id) on delete cascade,
  name text not null check (length(trim(name)) between 1 and 500),
  type text not null check (type in ('normal','daily','weekly')),
  display_order integer not null default 0,
  generation integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id,user_id)
);
create index checklists_owner_order on public.checklists(user_id,display_order,id);
create table public.tasks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(user_id) on delete cascade,
  checklist_id uuid not null,
  title text not null check (length(trim(title)) between 1 and 1000),
  description text not null default '' check (length(description)<=20000),
  priority text not null default 'Medium' check (priority in ('Low','Medium','High')),
  due_date date,
  display_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key(checklist_id,user_id) references public.checklists(id,user_id) on delete cascade,
  unique(id,user_id)
);
create index tasks_list_order on public.tasks(checklist_id,display_order,id);
create index tasks_owner on public.tasks(user_id);
create table public.task_completions (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null,
  user_id uuid not null,
  period_key text not null,
  is_completed boolean not null,
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  foreign key(task_id,user_id) references public.tasks(id,user_id) on delete cascade,
  unique(task_id,period_key)
);
create index completions_owner on public.task_completions(user_id);
create table public.imports (
  user_id uuid not null references public.profiles(user_id) on delete cascade,
  source_id uuid not null,
  content_hash text not null,
  checklist_count integer not null,
  task_count integer not null,
  created_at timestamptz not null default now(),
  primary key(user_id,source_id)
);

alter table public.profiles enable row level security;
alter table public.checklists enable row level security;
alter table public.tasks enable row level security;
alter table public.task_completions enable row level security;
alter table public.imports enable row level security;
create policy own_profile on public.profiles for select to authenticated using(user_id=auth.uid());
create policy own_checklists on public.checklists for select to authenticated using(user_id=auth.uid());
create policy own_tasks on public.tasks for select to authenticated using(user_id=auth.uid());
create policy own_completions on public.task_completions for select to authenticated using(user_id=auth.uid());
create policy own_imports on public.imports for select to authenticated using(user_id=auth.uid());
revoke all on public.profiles,public.checklists,public.tasks,public.task_completions,public.imports from anon,authenticated;
grant select on public.profiles,public.checklists,public.tasks,public.task_completions,public.imports to authenticated;

-- Account wall calendar, with no dependency on a device's clock or timezone.
create function private.period_key(kind text, generation integer, zone text, instant timestamptz)
returns text language sql stable set search_path='' as $$
select kind || ':' || generation::text || case when kind='normal' then '' else ':' ||
(case when kind='weekly' then date_trunc('week', (instant at time zone zone)-interval '6 hours')::date
else ((instant at time zone zone)-interval '6 hours')::date end)::text end
$$;
create function private.next_reset(kind text, zone text, instant timestamptz)
returns timestamptz language sql stable set search_path='' as $$
select case when kind='normal' then null else
((case when kind='weekly' then date_trunc('week',(instant at time zone zone)-interval '6 hours')+interval '7 days'
else date_trunc('day',(instant at time zone zone)-interval '6 hours')+interval '1 day' end)+interval '6 hours') at time zone zone end
$$;

create function public.checklist_snapshot() returns jsonb
language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid(); p public.profiles; answer jsonb;
begin
 if u is null then raise exception 'Sign in first' using errcode='42501'; end if;
 insert into public.profiles(user_id) values(u) on conflict do nothing;
 -- Prevent any mutation during aggregation: all rows in this snapshot share one revision.
 select * into p from public.profiles where user_id=u for share;
 select jsonb_build_object('user_id',u,'revision',p.revision,'timezone',p.timezone,'settings',p.settings,'server_time',now(),
 'checklists',coalesce((select jsonb_agg(to_jsonb(c)||jsonb_build_object('period_key',private.period_key(c.type,c.generation,p.timezone,now()),'next_reset',private.next_reset(c.type,p.timezone,now()),'next_reset_local',to_char(private.next_reset(c.type,p.timezone,now()) at time zone p.timezone,'YYYY-MM-DD HH24:MI')) order by c.display_order,c.id) from public.checklists c where c.user_id=u),'[]'::jsonb),
 'tasks',coalesce((select jsonb_agg(to_jsonb(t)||jsonb_build_object('is_completed',coalesce(tc.is_completed,false)) order by t.display_order,t.id) from public.tasks t join public.checklists c on c.id=t.checklist_id left join public.task_completions tc on tc.task_id=t.id and tc.period_key=private.period_key(c.type,c.generation,p.timezone,now()) where t.user_id=u),'[]'::jsonb)) into answer;
 return answer;
end $$;

create function public.checklist_mutate(expected_revision bigint, operation text, payload jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 u uuid:=auth.uid(); p public.profiles; c public.checklists; t public.tasks; item record;
 ident uuid; result_id uuid; ids uuid[]; current_key text; new_kind text;
begin
 if u is null then raise exception 'Sign in first' using errcode='42501'; end if;
 insert into public.profiles(user_id) values(u) on conflict do nothing;
 select * into p from public.profiles where user_id=u for update;
 if p.revision<>expected_revision then raise exception 'CONFLICT: Account changed on another device. Refresh and review your edits.' using errcode='40001'; end if;
 ident:=nullif(payload->>'id','')::uuid;
 if operation in ('edit_checklist','delete_checklist','duplicate','clear_completed') then
   select * into c from public.checklists where id=ident and user_id=u;
   if not found then raise exception 'Checklist no longer exists' using errcode='42501'; end if;
 end if;
 if operation in ('edit_task','delete_task','complete') then
   select * into t from public.tasks where id=ident and user_id=u;
   if not found then raise exception 'Task no longer exists' using errcode='42501'; end if;
   select * into c from public.checklists where id=t.checklist_id and user_id=u;
 end if;
 case operation
 when 'create_checklist' then
   result_id:=coalesce(ident,gen_random_uuid());
   insert into public.checklists(id,user_id,name,type,display_order) values(result_id,u,trim(payload->>'name'),payload->>'type',coalesce((select max(display_order)+1 from public.checklists where user_id=u),0));
 when 'edit_checklist' then
   new_kind:=payload->>'type';
   update public.checklists set name=trim(payload->>'name'),type=new_kind,generation=generation+case when type<>new_kind then 1 else 0 end,updated_at=now() where id=ident;
 when 'delete_checklist' then delete from public.checklists where id=ident;
 when 'create_task' then
   select * into c from public.checklists where id=(payload->>'checklist_id')::uuid and user_id=u;
   if not found then raise exception 'Checklist no longer exists' using errcode='42501'; end if;
   result_id:=coalesce(ident,gen_random_uuid());
   insert into public.tasks(id,user_id,checklist_id,title,description,priority,due_date,display_order) values(result_id,u,c.id,trim(payload->>'title'),coalesce(payload->>'description',''),coalesce(payload->>'priority','Medium'),nullif(payload->>'due_date','')::date,coalesce((select max(display_order)+1 from public.tasks where checklist_id=c.id),0));
 when 'edit_task' then
   update public.tasks set title=trim(payload->>'title'),description=coalesce(payload->>'description',''),priority=payload->>'priority',due_date=nullif(payload->>'due_date','')::date,updated_at=now() where id=ident;
 when 'delete_task' then delete from public.tasks where id=ident;
 when 'complete' then
   current_key:=private.period_key(c.type,c.generation,p.timezone,now());
   if payload->>'period_key' is distinct from current_key then raise exception 'PERIOD_CHANGED: This checklist has entered a new period. Refresh before completing it.' using errcode='40001'; end if;
   insert into public.task_completions(task_id,user_id,period_key,is_completed,completed_at) values(ident,u,current_key,(payload->>'completed')::boolean,case when (payload->>'completed')::boolean then now() end)
   on conflict(task_id,period_key) do update set is_completed=excluded.is_completed,completed_at=excluded.completed_at,updated_at=now();
 when 'clear_completed' then
   current_key:=private.period_key(c.type,c.generation,p.timezone,now());
   if payload->>'period_key' is distinct from current_key then raise exception 'PERIOD_CHANGED: Refresh before clearing completed tasks.' using errcode='40001'; end if;
   delete from public.tasks a using public.task_completions b where a.checklist_id=c.id and a.id=b.task_id and b.period_key=current_key and b.is_completed;
 when 'duplicate' then
   result_id:=coalesce(nullif(payload->>'new_id','')::uuid,gen_random_uuid());
   insert into public.checklists(id,user_id,name,type,display_order) values(result_id,u,c.name||' (copy)',c.type,coalesce((select max(display_order)+1 from public.checklists where user_id=u),0));
   for item in select * from public.tasks where checklist_id=c.id order by display_order,id loop
     ident:=gen_random_uuid();
     insert into public.tasks(id,user_id,checklist_id,title,description,priority,due_date,display_order) values(ident,u,result_id,item.title,item.description,item.priority,item.due_date,item.display_order);
     insert into public.task_completions(task_id,user_id,period_key,is_completed,completed_at)
     select ident,u,private.period_key(c.type,1,p.timezone,now()),true,now() from public.task_completions where task_id=item.id and period_key=private.period_key(c.type,c.generation,p.timezone,now()) and is_completed;
   end loop;
 when 'reorder' then
   select array_agg(value::uuid) into ids from jsonb_array_elements_text(payload->'ids');
   if ids is null or cardinality(ids)<>(select count(distinct value) from unnest(ids) value) then raise exception 'Invalid order'; end if;
   if payload->>'table'='checklists' then
     new_kind:=payload->>'type';
     if cardinality(ids)<>(select count(*) from public.checklists where user_id=u and type=new_kind) or exists(select 1 from unnest(ids) a where not exists(select 1 from public.checklists b where b.id=a and b.user_id=u and b.type=new_kind)) then raise exception 'CONFLICT: Checklist order changed' using errcode='40001'; end if;
     update public.checklists b set display_order=a.n::integer,updated_at=now() from unnest(ids) with ordinality a(id,n) where b.id=a.id;
   elsif payload->>'table'='tasks' then
     ident:=(payload->>'checklist_id')::uuid;
     if not exists(select 1 from public.checklists where id=ident and user_id=u) or cardinality(ids)<>(select count(*) from public.tasks where checklist_id=ident) or exists(select 1 from unnest(ids) a where not exists(select 1 from public.tasks b where b.id=a and b.user_id=u and b.checklist_id=ident)) then raise exception 'CONFLICT: Task order changed' using errcode='40001'; end if;
     update public.tasks b set display_order=a.n::integer,updated_at=now() from unnest(ids) with ordinality a(id,n) where b.id=a.id;
   else raise exception 'Invalid ordering target'; end if;
 when 'settings' then
   if exists(select 1 from jsonb_object_keys(payload) a where a not in ('light','completed_bottom','confirm')) then raise exception 'Unknown shared setting'; end if;
   if exists(select 1 from jsonb_each(payload) a where jsonb_typeof(a.value)<>'boolean') then raise exception 'Settings must be boolean'; end if;
   update public.profiles set settings=settings||payload where user_id=u;
 when 'timezone' then
   if not exists(select 1 from pg_catalog.pg_timezone_names where name=payload->>'timezone') then raise exception 'Choose a valid IANA timezone'; end if;
   -- New generation keeps earlier timezone histories distinct.
   update public.checklists set generation=generation+1,updated_at=now() where user_id=u and type<>'normal';
   update public.profiles set timezone=payload->>'timezone' where user_id=u;
 else raise exception 'Unsupported operation';
 end case;
 update public.profiles set revision=revision+1,updated_at=now() where user_id=u returning revision into p.revision;
 return jsonb_build_object('id',coalesce(result_id,ident),'revision',p.revision);
end $$;

-- One atomic, explicitly confirmed import. Repeating a source never recreates deleted imports.
create function public.checklist_import(expected_revision bigint, manifest jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid(); p public.profiles; old public.imports; c jsonb; t jsonb; source uuid; result jsonb;
begin
 if u is null then raise exception 'Sign in first' using errcode='42501'; end if;
 insert into public.profiles(user_id) values(u) on conflict do nothing;
 select * into p from public.profiles where user_id=u for update;
 source:=(manifest->>'source_id')::uuid;
 select * into old from public.imports where user_id=u and source_id=source;
 if found then
   if old.content_hash<>manifest->>'content_hash' then raise exception 'This SQLite source was already imported with different contents. Review changes manually; nothing was overwritten.'; end if;
   return to_jsonb(old)||jsonb_build_object('already_imported',true);
 end if;
 if p.revision<>expected_revision then raise exception 'CONFLICT: Refresh and preview the import again' using errcode='40001'; end if;
 if exists(select 1 from jsonb_each(coalesce(manifest->'settings','{}'::jsonb)) a where a.key not in ('light','completed_bottom','confirm') or jsonb_typeof(a.value)<>'boolean') then raise exception 'Invalid imported settings'; end if;
 if jsonb_array_length(manifest->'checklists')>10000 or jsonb_array_length(manifest->'tasks')>100000 then raise exception 'Import too large'; end if;
 for c in select value from jsonb_array_elements(manifest->'checklists') loop
   insert into public.checklists(id,user_id,name,type,display_order) values((c->>'id')::uuid,u,c->>'name',c->>'type',(c->>'display_order')::integer);
 end loop;
 for t in select value from jsonb_array_elements(manifest->'tasks') loop
   if not exists(select 1 from jsonb_array_elements(manifest->'checklists') imported(value) where imported.value->>'id'=t->>'checklist_id') then raise exception 'Imported task references a checklist outside the import'; end if;
   insert into public.tasks(id,user_id,checklist_id,title,description,priority,due_date,display_order) values((t->>'id')::uuid,u,(t->>'checklist_id')::uuid,t->>'title',t->>'description',t->>'priority',nullif(t->>'due_date','')::date,(t->>'display_order')::integer);
   -- Only transfer completion when the source's processed period matches the account period preview.
   if coalesce((t->>'is_completed')::boolean,false) then
     select value into c from jsonb_array_elements(manifest->'checklists') where value->>'id'=t->>'checklist_id';
     if c->>'type'='normal' or c->>'last_processed_period'=split_part(private.period_key(c->>'type',1,p.timezone,now()),':',3) then
       insert into public.task_completions(task_id,user_id,period_key,is_completed,completed_at) values((t->>'id')::uuid,u,private.period_key(c->>'type',1,p.timezone,now()),true,now());
     end if;
   end if;
 end loop;
 update public.profiles set settings=settings||coalesce(manifest->'settings','{}'::jsonb),revision=revision+1,updated_at=now() where user_id=u;
 insert into public.imports(user_id,source_id,content_hash,checklist_count,task_count) values(u,source,manifest->>'content_hash',jsonb_array_length(manifest->'checklists'),jsonb_array_length(manifest->'tasks')) returning to_jsonb(imports.*) into result;
 return result||jsonb_build_object('already_imported',false);
end $$;

revoke all on all functions in schema private from public,anon,authenticated;
revoke all on function public.checklist_snapshot(),public.checklist_mutate(bigint,text,jsonb),public.checklist_import(bigint,jsonb) from public,anon;
grant execute on function public.checklist_snapshot(),public.checklist_mutate(bigint,text,jsonb),public.checklist_import(bigint,jsonb) to authenticated;
-- Only owner-visible profile UPDATE events are needed: each mutation increments revision.
do $$ begin
 if exists(select 1 from pg_publication where pubname='supabase_realtime') then
   alter publication supabase_realtime add table public.profiles;
 end if;
end $$;
commit;
