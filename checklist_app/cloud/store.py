"""Desktop database adapter. Cloud writes are online-only and revision checked."""
from datetime import datetime, timezone
from uuid import uuid4
import json
import time

SHARED_SETTINGS = {'light', 'completed_bottom', 'confirm'}


class SyncError(RuntimeError):
    pass


class CloudDatabase:
    is_cloud = True

    def __init__(self, transport, cache, runner=lambda fn:fn()):
        self.transport = transport
        self.cache = cache
        self.runner = runner
        self.snapshot = cache.load() or {'user_id':cache.user_id,'revision':0,'settings':{},'timezone':'Asia/Seoul','checklists':[],'tasks':[]}
        self.online = False
        self.busy = False
        self.status = 'Offline • Read-only cached data'
        self.last_attempt = 0.0
        self.server_tick = None
        self.dirty = False
        self.last_error = None

    def refresh(self):
        if self.busy:
            return False
        self.busy = True
        self.last_attempt = time.monotonic()
        try:
            answer = self.runner(lambda:self.transport.snapshot())
            if answer['user_id'] != self.cache.user_id:
                raise SyncError('The signed-in account changed. Sign out and reopen cloud mode.')
            old = self.snapshot
            was_online = self.online
            self.cache.save(answer)
            self.snapshot = answer
            self.server_tick = time.monotonic()
            self.online = True
            self.status = f"Synced • {answer['timezone']}"
            self.last_error = None
            self.dirty = False
            return answer != old or not was_online
        except Exception:
            self.online = False
            self.status = 'Offline or session expired • Cached data is read-only • Retrying'
            # Do not put SDK error strings (potentially containing URLs/tokens) in the UI/logs.
            return False
        finally:
            self.busy = False

    def mutate(self, operation, payload, expected_revision=None):
        if self.busy or not self.online:
            raise SyncError('You are offline or a request is in progress. Your edit was not sent. Reconnect and try again; cached data remains readable.')
        if expected_revision is not None and expected_revision!=self.snapshot['revision']:
            raise SyncError('Cloud data changed while you were reviewing this action. Refresh and confirm it again.')
        self.busy = True
        revision = self.snapshot['revision']
        self.status = 'Saving to cloud…'
        try:
            result = self.runner(lambda:self.transport.mutate(revision,operation,payload))
        except Exception as error:
            self.online = False
            self.status = 'Not saved or outcome uncertain • Refresh before retrying'
            # Preserve entered values in the caller/editor; never retry writes automatically.
            code = getattr(error,'code',None)
            if code == '40001':
                message = 'Another device changed this account or the reset period changed. Refresh, review your edits, and save again.'
            else:
                message = 'Cloud save could not be confirmed. Refresh to see whether it arrived before retrying. Your entered text is still available in the editor.'
            self.last_error = {'operation':operation,'payload':payload}
            raise SyncError(message) from None
        finally:
            self.busy = False
        if not self.refresh():
            # A successful write may have the same data except revision; refresh returns False on failure.
            if not self.online:
                raise SyncError('The server accepted the change, but the updated view could not be downloaded. Reconnect before editing again.')
        return result.get('id')

    def checklists(self):
        return sorted(self.snapshot['checklists'], key=lambda x:(x['display_order'],x['id']))

    def tasks(self, ident):
        return sorted([t for t in self.snapshot['tasks'] if t['checklist_id']==ident],key=lambda x:(x['display_order'],x['id']))

    def setting(self, key, default=None):
        if key in SHARED_SETTINGS:
            return self.snapshot['settings'].get(key,default)
        return self.cache.setting(key,default)

    def set_setting(self, key, value):
        if key in SHARED_SETTINGS:
            self.mutate('settings',{key:value})
        else:
            self.cache.set_setting(key,value)

    def save_shared_settings(self, settings):
        self.mutate('settings',settings)

    def create_checklist(self, name, kind, new_id=None):
        return self.mutate('create_checklist',{'id':new_id or str(uuid4()),'name':name.strip(),'type':kind})

    def edit_checklist(self, ident, name, kind):
        return self.mutate('edit_checklist',{'id':ident,'name':name.strip(),'type':kind})

    def delete_checklist(self, ident, expected_revision=None):
        return self.mutate('delete_checklist',{'id':ident},expected_revision)

    def duplicate(self, ident):
        return self.mutate('duplicate',{'id':ident,'new_id':str(uuid4())})

    def save_task(self, checklist, title, description='', priority='Medium', due_date=None, ident=None, new_id=None):
        return self.mutate('edit_task' if ident else 'create_task',{'id':ident or new_id or str(uuid4()),'checklist_id':checklist,'title':title.strip(),'description':description,'priority':priority,'due_date':due_date})

    def complete(self, ident, completed, displayed_period=None, expected_revision=None):
        task = next(t for t in self.snapshot['tasks'] if t['id']==ident)
        checklist = next(c for c in self.checklists() if c['id']==task['checklist_id'])
        return self.mutate('complete',{'id':ident,'completed':completed,'period_key':displayed_period or checklist['period_key']},expected_revision)

    def delete_task(self, ident, expected_revision=None):
        return self.mutate('delete_task',{'id':ident},expected_revision)

    def clear_completed(self, ident, displayed_period=None, expected_revision=None):
        checklist = next(c for c in self.checklists() if c['id']==ident)
        return self.mutate('clear_completed',{'id':ident,'period_key':displayed_period or checklist['period_key']},expected_revision)

    def reorder(self, table, identifiers):
        if not identifiers:
            return
        payload = {'table':table,'ids':identifiers}
        if table=='checklists':
            payload['type'] = next(c['type'] for c in self.checklists() if c['id']==identifiers[0])
        else:
            payload['checklist_id'] = next(t['checklist_id'] for t in self.snapshot['tasks'] if t['id']==identifiers[0])
        return self.mutate('reorder',payload)

    def reset_due(self):
        if not self.busy and (self.dirty or time.monotonic()-self.last_attempt>=15 or self.boundary_due()):
            return self.refresh()
        return False

    def boundary_due(self):
        if not self.online or self.server_tick is None or time.monotonic()-self.last_attempt < 1:
            return False
        server = datetime.fromisoformat(self.snapshot['server_time'].replace('Z','+00:00'))
        elapsed = time.monotonic()-self.server_tick
        return any(c.get('next_reset') and (datetime.fromisoformat(c['next_reset'].replace('Z','+00:00'))-server).total_seconds()<=elapsed for c in self.checklists())

    def clock(self):
        return datetime.now(timezone.utc)

    def reset_text(self, row):
        if row['type']=='normal':
            return 'Normal • No automatic reset'
        return f"{row['type'].title()} • Next reset: {row.get('next_reset_local',row['next_reset'])} • {self.snapshot['timezone']}" + ('' if self.online else ' • Last known period (offline)')

    def backup(self, destination):
        with open(destination,'x',encoding='utf-8') as output:
            json.dump(self.snapshot,output,indent=2)

    def close(self):
        self.cache.close()


class SupabaseTransport:
    def __init__(self, client):
        self.client = client

    def snapshot(self):
        return self.client.rpc('checklist_snapshot').execute().data

    def mutate(self, revision, operation, payload):
        return self.client.rpc('checklist_mutate',{'expected_revision':revision,'operation':operation,'payload':payload}).execute().data

    def import_manifest(self, revision, manifest):
        return self.client.rpc('checklist_import',{'expected_revision':revision,'manifest':manifest}).execute().data
