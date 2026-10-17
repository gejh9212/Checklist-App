import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:checklist_mobile/controller.dart';

class MemoryCache implements SnapshotCache {
  Json? data;
  @override
  Future<Json?> load() async => data;
  @override
  Future<void> save(Json snapshot) async { data = snapshot; }
}
class TestApi implements CloudApi {
  bool disconnected = false;
  int writes = 0;
  int revision = 0;
  String account = 'user-a';
  final events = StreamController<void>.broadcast();
  @override
  Stream<void> get changes => events.stream;
  @override
  Future<Json> snapshot() async {
    if(disconnected) { throw StateError('Disconnected'); }
    return {'user_id':account,'revision':revision,'settings':{},'timezone':'Asia/Seoul','server_time':'2026-10-18T20:00:00Z',
      'checklists':[{'id':'list','name':'Daily','type':'daily','display_order':0,'period_key':'daily:1:2026-10-18','next_reset':'2026-10-18T21:00:00Z','next_reset_local':'2026-10-19 06:00'}],
      'tasks':[{'id':'task','checklist_id':'list','title':'Water','description':'A glass','priority':'High','due_date':null,'display_order':0,'is_completed':writes>0}]};
  }
  @override
  Future<void> mutate(int expected, String operation, Json payload) async {
    if(disconnected || expected!=revision) { throw StateError('Conflict or disconnected'); }
    if(operation=='complete') { expect(payload['period_key'],'daily:1:2026-10-18'); }
    writes++; revision++;
  }
  @override
  Future<void> close() async => events.close();
}

void main() {
  test('offline cache is readable, edits blocked, reconnect fetches latest',() async {
    final api=TestApi(); final cache=MemoryCache();
    final controller=ChecklistController(api,cache,'user-a');
    addTearDown(controller.dispose);
    await controller.start();
    expect(controller.online,isTrue);
    api.disconnected=true;
    await controller.refresh();
    expect(controller.online,isFalse);
    expect(controller.tasks('list').single['title'],'Water');
    await expectLater(controller.complete(controller.tasks('list').single,true),throwsStateError);
    expect(api.writes,0);
    api.disconnected=false;
    await controller.refresh();
    await controller.complete(controller.tasks('list').single,true);
    expect(controller.tasks('list').single['is_completed'],isTrue);
  });
  test('account mismatch never replaces this users cache',() async {
    final api=TestApi(); final cache=MemoryCache();
    final controller=ChecklistController(api,cache,'user-a');
    addTearDown(controller.dispose);
    await controller.start();
    api.account='user-b';
    await controller.refresh();
    expect(controller.online,isFalse);
    expect(cache.data!['user_id'],'user-a');
  });
  test('edits from an old editor revision are rejected without sending',() async {
    final api=TestApi();
    final controller=ChecklistController(api,MemoryCache(),'user-a');
    addTearDown(controller.dispose);
    await controller.start();
    final oldRevision=controller.revision;
    api.revision++;
    await controller.refresh();
    await expectLater(controller.write('edit_task',{'id':'task','title':'Old draft'},expectedRevision:oldRevision),throwsStateError);
    expect(api.writes,0);
  });
  test('failed writes preserve draft and require refresh before another write',() async {
    final api=TestApi();
    final controller=ChecklistController(api,MemoryCache(),'user-a');
    addTearDown(controller.dispose);
    await controller.start();
    api.disconnected=true;
    await expectLater(controller.write('edit_task',{'id':'task','title':'Keep typed text'}),throwsStateError);
    expect(controller.unsavedDraft!['payload']['title'],'Keep typed text');
    expect(controller.online,isFalse);
  });
}
