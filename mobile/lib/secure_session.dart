import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

const secureStorage = FlutterSecureStorage(
  aOptions: AndroidOptions(encryptedSharedPreferences: true),
  iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
);

class SecureSessionStorage extends LocalStorage {
  SecureSessionStorage(this.namespace);
  final String namespace;
  String get key => 'checklist-session-$namespace';
  @override
  Future<void> initialize() async {}
  @override
  Future<bool> hasAccessToken() async => (await accessToken()) != null;
  @override
  Future<String?> accessToken() => secureStorage.read(key: key);
  @override
  Future<void> persistSession(String persistSessionString) => secureStorage.write(key: key, value: persistSessionString);
  @override
  Future<void> removePersistedSession() => secureStorage.delete(key: key);
}
