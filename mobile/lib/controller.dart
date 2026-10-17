import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

typedef Json = Map<String, dynamic>;

abstract class CloudApi {
  Future<Json> snapshot();
  Future<void> mutate(int revision, String operation, Json payload);
  Stream<void> get changes;
  Future<void> close();
}

class SupabaseApi implements CloudApi {
  SupabaseApi(this.client, this.userId) {
    channel = client.channel('checklist-account-$userId')
      .onPostgresChanges(event: PostgresChangeEvent.update, schema: 'public', table: 'profiles',
        filter: PostgresChangeFilter(type: PostgresChangeFilterType.eq, column: 'user_id', value: userId),
        callback: (_) => events.add(null))
      .subscribe((status, error) => events.add(null));
  }
  final SupabaseClient client;
  final String userId;
  final events = StreamController<void>.broadcast();
  late final RealtimeChannel channel;
  @override
  Stream<void> get changes => events.stream;
  @override
  Future<Json> snapshot() async => Map<String,dynamic>.from(await client.rpc('checklist_snapshot'));
  @override
  Future<void> mutate(int revision, String operation, Json payload) async {
    if (client.auth.currentUser?.id!=userId) { throw StateError('The signed-in account changed. Reopen the checklist.'); }
    await client.rpc('checklist_mutate', params: {'expected_revision':revision,'operation':operation,'payload':payload});
  }
  @override
  Future<void> close() async {
    await client.removeChannel(channel);
    await events.close();
  }
}

abstract class SnapshotCache {
  Future<Json?> load();
  Future<void> save(Json data);
}

class FileSnapshotCache implements SnapshotCache {
  FileSnapshotCache(this.namespace, this.userId);
  final String namespace;
  final String userId;
  Future<File> file() async {
    final directory = await getApplicationSupportDirectory();
    return File('${directory.path}/checklist-$namespace-$userId.json');
  }
  @override
  Future<Json?> load() async {
    try {
      final data = Map<String,dynamic>.from(jsonDecode(await (await file()).readAsString()));
      return data['user_id']==userId ? data : null;
    } on FileSystemException { return null; }
    on FormatException { return null; }
  }
  @override
  Future<void> save(Json data) async {
    if (data['user_id']!=userId) { throw StateError('Account cache mismatch'); }
    final destination = await file();
    await destination.parent.create(recursive: true);
    final temporary = File('${destination.path}.tmp');
    await temporary.writeAsString(jsonEncode(data), flush: true);
    await temporary.rename(destination.path);
  }
}

class ChecklistController extends ChangeNotifier {
  ChecklistController(this.api, this.cache, this.userId);
  final CloudApi api;
  final SnapshotCache cache;
  final String userId;
  Json data = {'revision':0,'settings':{},'checklists':<Json>[],'tasks':<Json>[],'timezone':'Asia/Seoul'};
  bool online = false;
  bool busy = false;
  bool closed = false;
  String status = 'Connecting…';
  Timer? timer;
  StreamSubscription<void>? subscription;
  Stopwatch serverElapsed = Stopwatch();
  DateTime? serverTime;
  Json? unsavedDraft;

  List<Json> get checklists => List<Json>.from((data['checklists'] as List).map((r)=>Map<String,dynamic>.from(r)));
  List<Json> tasks(String id) => List<Json>.from((data['tasks'] as List).where((t)=>t['checklist_id']==id).map((r)=>{...Map<String,dynamic>.from(r),'period_key':checklists.firstWhere((c)=>c['id']==id)['period_key'],'view_revision':revision}))
    ..sort((a,b) { final order = (a['display_order'] as int).compareTo(b['display_order'] as int); return order!=0 ? order : (a['id'] as String).compareTo(b['id'] as String); });
  Json get settings => Map<String,dynamic>.from(data['settings'] as Map);
  int get revision => data['revision'] as int;

  Future<void> start() async {
    final saved = await cache.load();
    if (closed) { return; }
    if (saved!=null && saved['user_id']==userId) { data=saved; }
    await refresh();
    if (closed) { return; }
    subscription = api.changes.listen((_) { unawaited(refresh()); });
    timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (serverElapsed.elapsed.inSeconds>=15 || boundaryDue() || !online) {
        // Retry at most once per 15 seconds while disconnected.
        if (online || serverElapsed.elapsed.inSeconds>=15) { unawaited(refresh()); }
      }
    });
  }

  bool boundaryDue() {
    if (serverTime==null || !online) { return false; }
    final estimated = serverTime!.add(serverElapsed.elapsed);
    return checklists.any((c)=>c['next_reset']!=null && !DateTime.parse(c['next_reset'] as String).isAfter(estimated));
  }

  Future<void> refresh() async {
    if (closed || busy) { return; }
    busy = true;
    try {
      final snapshot = await api.snapshot().timeout(const Duration(seconds: 12));
      if (closed) { return; }
      if (snapshot['user_id']!=userId) { throw StateError('Account changed'); }
      await cache.save(snapshot);
      if (closed) { return; }
      data = snapshot;
      serverTime = DateTime.parse(snapshot['server_time'] as String);
      online = true;
      status = 'Synced • ${data['timezone']}';
    } catch (_) {
      online = false;
      status = 'Offline or session expired • Cached data is read-only';
    } finally {
      serverElapsed..reset()..start();
      busy = false;
      if (!closed) { notifyListeners(); }
    }
  }

  Future<void> write(String operation, Json payload, {int? expectedRevision}) async {
    if (closed) { throw StateError('This account view was closed. Sign in again before editing.'); }
    if (!online || busy) { throw StateError('Offline or busy. No change was sent. Reconnect and try again.'); }
    if (expectedRevision!=null && expectedRevision!=revision) {
      throw StateError('Another device changed this account while you were editing. Your draft is preserved; review the latest data before saving again.');
    }
    busy = true;
    status = 'Saving…';
    notifyListeners();
    try {
      await api.mutate(revision,operation,payload).timeout(const Duration(seconds: 12));
      unsavedDraft = null;
    } catch (_) {
      unsavedDraft = {'operation':operation,'payload':payload};
      online = false;
      status = 'Save not confirmed • Refresh before retrying';
      rethrow;
    } finally {
      busy = false;
      if (!closed) { notifyListeners(); }
    }
    await refresh();
    if (!online) { throw StateError('The change was accepted, but the latest view could not be downloaded. Reconnect before editing again.'); }
  }

  Future<void> complete(Json task, bool value) {
    final checklist = checklists.firstWhere((c)=>c['id']==task['checklist_id']);
    return write('complete',{'id':task['id'],'completed':value,'period_key':task['period_key'] ?? checklist['period_key']},expectedRevision:task['view_revision'] as int?);
  }

  @override
  void dispose() {
    closed = true;
    timer?.cancel();
    unawaited(subscription?.cancel());
    unawaited(api.close());
    super.dispose();
  }
}
