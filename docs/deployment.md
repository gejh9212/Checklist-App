# Build and install applications

No application binaries have been built on Windows, Android, or iOS in the Linux cloud workspace. Native platform checks are mandatory before distribution. No app-store publication is required for personal Android use.

## Windows 10/11

Install Python 3.12+ and dependencies as described in setup.md. From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

This invokes the pinned PyInstaller and includes keyring backend, Supabase, and timezone modules. Test `dist\ChecklistApp.exe` on Windows. Local-only mode remains the default. To use cloud mode, place your private `.env` configuration in the folder you launch from, or configure the two client environment variables, then run:

```powershell
.\dist\ChecklistApp.exe --cloud
```

The publishable client configuration is not a secret, but keep local configuration outside Git. Never bundle sessions, database files, backups, service-role keys, or secret keys. Copying a new EXE does not replace `%LOCALAPPDATA%\ChecklistApp\checklists.db`. Verify both local and cloud startup on a clean Windows machine before relying on the EXE.

## Android APK (install directly on your phone)

1. Install Android Studio, then the Android SDK, current platform tools, SDK command-line tools, and a compatible emulator image. Flutter 3.35.7's template targets Android SDK 36. Install that SDK platform and the NDK requested by `flutter doctor`/Gradle.
2. Install Flutter 3.35.7+ stable and a Java 17+ JDK supported by that Flutter/Gradle combination. Android Studio supplies a suitable JDK; run `flutter doctor -v` to see which one is used. The included Gradle wrapper is 8.12 with an official distribution SHA256 pin; its packaged wrapper was also checked against Gradle's official SHA256.
3. Run `flutter doctor` and `flutter doctor --android-licenses`. Read and accept required licenses yourself. Do not have a script accept licenses blindly.
4. In `mobile/`, create `config.local.json` from the example and fill in the two client values. Run `flutter pub get`, `flutter analyze`, and `flutter test`. Generate and retain `pubspec.lock` after a successful dependency resolution; it could not be generated in the cloud workspace because official SDK downloads were blocked. Direct package versions are pinned, but full transitive build reproducibility is pending that lockfile.
5. For a quick development run, enable **Developer options → USB debugging** on your phone, connect it, authorize your computer on the phone, run `flutter devices`, then `flutter run --dart-define-from-file=config.local.json`. Debug installs use a development signing key.

For a release APK, create and preserve your own signing key. Do not commit it. In PowerShell:

```powershell
keytool -genkeypair -v -keystore "$env:USERPROFILE\checklist-upload.jks" -keyalg RSA -keysize 2048 -validity 10000 -alias checklist
```

This prompts for private passwords: enter them locally, not in chat. Save the keystore somewhere backed up and secure. Create ignored `mobile/android/key.properties` locally:

```properties
storeFile=C:/Users/YOUR_NAME/checklist-upload.jks
storePassword=YOUR_LOCAL_KEYSTORE_PASSWORD
keyPassword=YOUR_LOCAL_KEY_PASSWORD
keyAlias=checklist
```

These are placeholders, not credentials supplied by the application. Use forward slashes in the path. Restrict this file to your OS user. Do not paste real passwords into a GitHub issue, commit, or chat. Release builds refuse to silently use the debug key.

From `mobile/`:

```powershell
flutter build apk --release --dart-define-from-file=config.local.json
```

The output is `mobile/build/app/outputs/flutter-apk/app-release.apk`. Transfer it to your phone and open it, allowing installation from that file source when Android asks. Or install over USB:

```powershell
adb install -r build/app/outputs/flutter-apk/app-release.apk
```

Keep the same application ID and signing key for future updates. A differently signed build cannot update the original. Switching from a debug install to a release install may require removing the debug app, which removes its read cache; first confirm all important data exists in Supabase. Never uninstall your only source of unsynchronized personal data. Cloud mode does not queue offline edits, and the original Windows SQLite file remains independent.

## iOS on macOS

A Mac with Xcode and its command-line tools is required. Install a Flutter-compatible Xcode, CocoaPods, and the iOS SDK; run `flutter doctor`. The included project targets iOS 13 or newer. Flutter, plugin, or Xcode upgrades may raise that minimum. Linux/Windows cannot produce or sign an iOS application.

On the Mac, from `mobile/`:

```bash
flutter pub get
flutter analyze
flutter test
cd ios
pod install
open Runner.xcworkspace
```

Use `Runner.xcworkspace`, not just the `.xcodeproj`, so CocoaPods plugins are included. In Xcode select the Runner target, **Signing & Capabilities**, select your own development team, and use an application bundle ID available to your team. Keychain entitlements are included for secure session storage. Keep bundle IDs/signing consistent across updates.

A free Apple ID can be used for limited personal-device development with restrictions and periodic re-signing. An Apple Developer Program membership is generally needed for distribution, TestFlight, and App Store signing. Follow Apple's current terms. Connect your iPhone, trust the Mac, enable Developer Mode if prompted, and run:

```bash
flutter run --dart-define-from-file=config.local.json
```

After configuring a paid signing team and provisioning where required:

```bash
flutter build ipa --release --dart-define-from-file=config.local.json
```

Use Xcode Organizer for the permitted distribution method. No iOS archive or signed IPA has been produced here.

## Supabase deployment and approvals

The SQL migration is supplied for review, not automatically applied to a hosted project. Do not run a custom server. Apply it only to your own new project after reviewing setup.md. Never put a service-role key in an app. Configure Supabase database backups separately. This work is on `upgrade/windows-mobile-sync`; it has not been pushed, merged, or deployed automatically.

Before production use, execute the two-account security checks and two-device synchronization checklist in testing.md, including hosted Auth, token refresh, Realtime, offline reconnection, and platform credential storage. Local tests emulate auth claims and cannot establish hosted JWT validation or device signing readiness.
