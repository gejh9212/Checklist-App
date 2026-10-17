import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:checklist_mobile/controller.dart';
import 'package:checklist_mobile/screens.dart';
import 'controller_test.dart' show TestApi, MemoryCache;

void main() {
  testWidgets('home displays progress and category headings on a small phone',(tester) async {
    tester.view.physicalSize=const Size(360,740);
    tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller=ChecklistController(TestApi(),MemoryCache(),'user-a');
    await controller.start();
    await tester.pumpWidget(MaterialApp(home:HomeScreen(controller:controller,onLogout:() async {})));
    expect(find.text('DAILY'),findsOneWidget);
    expect(find.text('0/1 completed • 0%'),findsOneWidget);
    expect(find.byType(LinearProgressIndicator),findsOneWidget);
    expect(tester.takeException(),isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
  });
}
