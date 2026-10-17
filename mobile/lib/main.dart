import 'dart:async';
import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'controller.dart';
import 'screens.dart';
import 'secure_session.dart';

const projectUrl = String.fromEnvironment('SUPABASE_URL');
const publishableKey = String.fromEnvironment('SUPABASE_PUBLISHABLE_KEY');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final uri = Uri.tryParse(projectUrl);
  if (uri==null || uri.scheme!='https' || uri.host.isEmpty || uri.userInfo.isNotEmpty || uri.path.isNotEmpty || !publishableKey.startsWith('sb_publishable_')) {
    runApp(const MaterialApp(home: Scaffold(body: SafeArea(child: Padding(padding: EdgeInsets.all(24), child: Text('Configure SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY using --dart-define-from-file=config.local.json. Use a publishable key, never a secret or service-role key. See docs/setup.md.'))))));
    return;
  }
  final namespace = sha256.convert(utf8.encode(projectUrl)).toString().substring(0,24);
  final storage = SecureSessionStorage(namespace);
  try {
    await Supabase.initialize(url: projectUrl, publishableKey: publishableKey, debug: false,
      authOptions: FlutterAuthClientOptions(localStorage: storage, detectSessionInUri: false));
    runApp(ChecklistApp(namespace: namespace, storage: storage));
  } catch (_) {
    runApp(const MaterialApp(home: Scaffold(body: SafeArea(child: Padding(padding: EdgeInsets.all(24), child: Text('Could not initialize secure sign-in. Unlock your device, check the client configuration, and restart. Your checklists were not changed.'))))));
  }
}

class ChecklistApp extends StatefulWidget {
  const ChecklistApp({super.key, required this.namespace, required this.storage});
  final String namespace;
  final SecureSessionStorage storage;
  @override
  State<ChecklistApp> createState() => _ChecklistAppState();
}

class _ChecklistAppState extends State<ChecklistApp> with WidgetsBindingObserver {
  ChecklistController? controller;
  StreamSubscription<AuthState>? auth;
  bool forcedLogout = false;
  SupabaseClient get client => Supabase.instance.client;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    selectAccount();
    auth = client.auth.onAuthStateChange.listen((event) {
      if (event.event==AuthChangeEvent.signedIn) { forcedLogout=false; }
      if (mounted) { setState(selectAccount); }
    });
  }
  void selectAccount() {
    final user = forcedLogout ? null : client.auth.currentUser;
    if (user?.id==controller?.userId) { return; }
    controller?.dispose();
    controller = user==null ? null : ChecklistController(SupabaseApi(client,user.id),FileSnapshotCache(widget.namespace,user.id),user.id);
    if (controller!=null) { unawaited(controller!.start()); }
  }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state==AppLifecycleState.resumed) { unawaited(controller?.refresh()); }
  }
  Future<void> logout() async {
    try { await client.auth.signOut(scope: SignOutScope.local); } catch (_) { /* Local secure storage is cleared even when offline. */ }
    await widget.storage.removePersistedSession();
    if (mounted) { setState(() { forcedLogout=true; selectAccount(); }); }
  }
  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(auth?.cancel());
    controller?.dispose();
    super.dispose();
  }
  ThemeData theme(Brightness brightness) => ThemeData(
    useMaterial3: true, brightness: brightness, colorSchemeSeed: const Color(0xff8193ff),
    scaffoldBackgroundColor: brightness==Brightness.dark ? const Color(0xff191c24) : const Color(0xfff1f3f8),
    inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(14)))),
  );
  @override
  Widget build(BuildContext context) {
    final current = controller;
    Widget application() => MaterialApp(title: 'ChecklistApp', theme: theme(Brightness.light), darkTheme: theme(Brightness.dark),
      themeMode: current?.settings['light']==true ? ThemeMode.light : ThemeMode.dark,
      home: current==null ? LoginScreen(client:client,onSignedIn:() { if(mounted) { setState(() { forcedLogout=false; selectAccount(); }); } }) : HomeScreen(controller:current,onLogout:logout));
    return current==null ? application() : AnimatedBuilder(animation:current,builder:(_,child)=>application());
  }
}

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key,required this.client,required this.onSignedIn});
  final SupabaseClient client;
  final VoidCallback onSignedIn;
  @override
  State<LoginScreen> createState()=>_LoginScreenState();
}
class _LoginScreenState extends State<LoginScreen> {
  final email=TextEditingController();
  final password=TextEditingController();
  bool busy=false;
  String message='Use the same email on Windows and mobile.';
  Future<void> submit(bool signup) async {
    if (email.text.trim().isEmpty || password.text.length<6) { setState(()=>message='Enter an email and a password of at least six characters.'); return; }
    setState(()=>busy=true);
    try {
      final result = signup ? await widget.client.auth.signUp(email:email.text.trim(),password:password.text) : await widget.client.auth.signInWithPassword(email:email.text.trim(),password:password.text);
      if (!mounted) { return; }
      password.clear();
      if (result.session!=null) { widget.onSignedIn(); }
      else { setState(()=>message='Check your email for the confirmation link. Then return here and sign in.'); }
    } catch (_) {
      if(mounted) { setState(()=>message='Sign-in failed. Check your email, password, connection, and email confirmation.'); }
    } finally { if(mounted) { setState(()=>busy=false); } }
  }
  @override
  void dispose() { email.dispose(); password.dispose(); super.dispose(); }
  @override
  Widget build(BuildContext context) => Scaffold(body: SafeArea(child: Center(child: SingleChildScrollView(padding:const EdgeInsets.all(24), child: ConstrainedBox(constraints:const BoxConstraints(maxWidth:440),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
    const Icon(Icons.checklist_rounded,size:64),const SizedBox(height:20),Text('ChecklistApp',style:Theme.of(context).textTheme.headlineLarge),const SizedBox(height:16),
    Text(message),const SizedBox(height:24),TextField(controller:email,keyboardType:TextInputType.emailAddress,autofillHints:const [AutofillHints.email],decoration:const InputDecoration(labelText:'Email')),
    const SizedBox(height:16),TextField(controller:password,obscureText:true,autofillHints:const [AutofillHints.password],decoration:const InputDecoration(labelText:'Password')),
    const SizedBox(height:24),FilledButton(onPressed:busy ? null : ()=>submit(false),child:Text(busy?'Connecting…':'Sign in')),
    TextButton(onPressed:busy ? null : ()=>submit(true),child:const Text('Create account')),
  ]))))));
}
