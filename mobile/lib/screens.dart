import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';
import 'controller.dart';

const categories = [('daily','DAILY',Color(0xff66aaff)),('weekly','WEEKLY',Color(0xffb69aff)),('normal','OTHER',Color(0xff69cdb1))];

Future<bool> confirm(BuildContext context, ChecklistController controller, String text) async {
  if (controller.settings['confirm']==false) { return true; }
  return await showDialog<bool>(context:context,builder:(context)=>AlertDialog(title:const Text('Please confirm'),content:Text(text),actions:[TextButton(onPressed:()=>Navigator.pop(context,false),child:const Text('Cancel')),FilledButton(onPressed:()=>Navigator.pop(context,true),child:const Text('Confirm'))])) ?? false;
}

Future<void> action(BuildContext context, Future<void> Function() callback) async {
  try { await callback(); }
  catch (error) {
    if (context.mounted) { ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text(error is StateError ? error.message.toString() : 'Cloud save could not be confirmed. Refresh before retrying; no offline edit queue is used.'))); }
  }
}

String resetLabel(Json row, String zone) => row['next_reset']==null ? 'No automatic reset' : 'Next reset: ${row['next_reset_local']} • $zone';

class SyncBanner extends StatelessWidget {
  const SyncBanner({super.key,required this.controller});
  final ChecklistController controller;
  @override
  Widget build(BuildContext context)=>Material(color:Theme.of(context).colorScheme.surfaceContainerHighest,child:Padding(padding:const EdgeInsets.symmetric(horizontal:16,vertical:6),child:Row(children:[Icon(controller.online?Icons.cloud_done_outlined:Icons.cloud_off_outlined,size:20),const SizedBox(width:10),Expanded(child:Text(controller.status,style:Theme.of(context).textTheme.bodySmall)),IconButton(tooltip:'Refresh cloud',onPressed:controller.busy?null:controller.refresh,icon:const Icon(Icons.refresh))])));
}

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key,required this.controller,required this.onLogout});
  final ChecklistController controller;
  final Future<void> Function() onLogout;
  @override
  Widget build(BuildContext context)=>AnimatedBuilder(animation:controller,builder:(context,child)=>Scaffold(
    appBar:AppBar(title:const Text('ChecklistApp'),actions:[IconButton(tooltip:'Settings',onPressed:()=>Navigator.push(context,MaterialPageRoute<void>(builder:(_)=>SettingsScreen(controller:controller,onLogout:onLogout))),icon:const Icon(Icons.settings_outlined))]),
    body:Column(children:[SyncBanner(controller:controller),Expanded(child:RefreshIndicator(onRefresh:controller.refresh,child:ListView(padding:const EdgeInsets.all(16),children:[
      if(controller.checklists.isEmpty) const Padding(padding:EdgeInsets.all(24),child:Text('No cloud checklists yet. Create one here, or import your existing SQLite data from Windows. Local data is never uploaded automatically.')),
      for(final category in categories) ...[
        Container(margin:const EdgeInsets.only(top:16,bottom:8),padding:const EdgeInsets.symmetric(horizontal:14,vertical:6),decoration:BoxDecoration(color:category.$3.withValues(alpha:0.14),borderRadius:BorderRadius.circular(12)),child:Row(children:[Expanded(child:Text(category.$2,style:TextStyle(color:category.$3,fontWeight:FontWeight.bold))),IconButton(tooltip:'Reorder ${category.$2.toLowerCase()} checklists',onPressed:controller.online&&!controller.busy?()=>reorderChecklists(context,controller,category.$1):null,icon:const Icon(Icons.swap_vert))])),
        for(final row in controller.checklists.where((r)=>r['type']==category.$1)) ChecklistCard(controller:controller,row:row),
      ],
      const SizedBox(height:80),
    ])))]),
    floatingActionButton:FloatingActionButton.extended(onPressed:controller.online&&!controller.busy?()=>checklistEditor(context,controller):null,icon:const Icon(Icons.add),label:const Text('Checklist')),
  ));
}

class ChecklistCard extends StatelessWidget {
  const ChecklistCard({super.key,required this.controller,required this.row});
  final ChecklistController controller;
  final Json row;
  @override
  Widget build(BuildContext context) {
    final tasks=controller.tasks(row['id'] as String);
    final completed=tasks.where((t)=>t['is_completed']==true).length;
    final progress=tasks.isEmpty?0.0:completed/tasks.length;
    return Card(clipBehavior:Clip.antiAlias,child:InkWell(onTap:()=>Navigator.push(context,MaterialPageRoute<void>(builder:(_)=>ChecklistScreen(controller:controller,id:row['id'] as String))),child:Padding(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
      Text(row['name'] as String,style:Theme.of(context).textTheme.titleLarge),const SizedBox(height:12),LinearProgressIndicator(value:progress,borderRadius:BorderRadius.circular(8),minHeight:6),const SizedBox(height:8),
      Text('$completed/${tasks.length} completed • ${(progress*100).round()}%'),const SizedBox(height:4),Text(resetLabel(row,controller.data['timezone'] as String),style:Theme.of(context).textTheme.bodySmall),
    ]))));
  }
}

Future<void> checklistEditor(BuildContext context,ChecklistController controller,{Json? row}) async {
  final name=TextEditingController(text:row?['name'] as String? ?? '');
  var kind=row?['type'] as String? ?? 'normal';
  var revision=controller.revision;
  final id=row?['id'] as String? ?? const Uuid().v4();
  var saving=false;
  String? error;
  await showDialog<void>(context:context,barrierDismissible:false,builder:(context)=>StatefulBuilder(builder:(context,setState)=>AlertDialog(title:Text(row==null?'Create checklist':'Checklist settings'),content:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,children:[
    TextField(controller:name,maxLength:500,decoration:const InputDecoration(labelText:'Name')),
    DropdownButtonFormField<String>(initialValue:kind,items:[for(final value in ['normal','daily','weekly']) DropdownMenuItem(value:value,child:Text(value))],onChanged:saving?null:(value)=>setState(()=>kind=value!),decoration:const InputDecoration(labelText:'Type')),
    if(error!=null) Padding(padding:const EdgeInsets.only(top:12),child:Text(error!)),
  ])),actions:[TextButton(onPressed:saving?null:()=>Navigator.pop(context),child:const Text('Cancel')),FilledButton(onPressed:saving?null:() async {
    if(name.text.trim().isEmpty) { setState(()=>error='Enter a checklist name.'); return; }
    setState(()=>saving=true);
    try {
      await controller.write(row==null?'create_checklist':'edit_checklist',{'id':id,'name':name.text.trim(),'type':kind},expectedRevision:revision);
      if(context.mounted) { Navigator.pop(context); }
    } catch (_) {
      await controller.refresh();
      revision=controller.revision;
      final latest=controller.checklists.where((c)=>c['id']==id).firstOrNull;
      if(context.mounted) { setState(()=>error='Save not confirmed or cloud changed. Your draft is kept. Current cloud name: ${latest?['name'] ?? '(not present)'}. Review before retrying.'); }
    } finally { if(context.mounted) { setState(()=>saving=false); } }
  },child:const Text('Save'))])));
  name.dispose();
}

Future<void> reorderChecklists(BuildContext context,ChecklistController controller,String kind) async {
  final rows=controller.checklists.where((r)=>r['type']==kind).toList();
  var revision=controller.revision;
  if(rows.length<2) { return; }
  await showModalBottomSheet<void>(context:context,showDragHandle:true,builder:(context)=>StatefulBuilder(builder:(context,setState)=>SizedBox(height:MediaQuery.sizeOf(context).height*0.6,child:ReorderableListView.builder(itemCount:rows.length,itemBuilder:(context,index)=>ListTile(key:ValueKey(rows[index]['id']),title:Text(rows[index]['name'] as String),leading:const Icon(Icons.drag_handle)),onReorder:(oldIndex,newIndex) async {
    if(!controller.online || controller.busy) { return; }
    if(newIndex>oldIndex) { newIndex--; }
    setState(()=>rows.insert(newIndex,rows.removeAt(oldIndex)));
    try { await controller.write('reorder',{'table':'checklists','type':kind,'ids':rows.map((r)=>r['id']).toList()},expectedRevision:revision); revision=controller.revision; }
    catch (_) { await controller.refresh(); if(context.mounted) { Navigator.pop(context); } }
  }))));
}

class ChecklistScreen extends StatefulWidget {
  const ChecklistScreen({super.key,required this.controller,required this.id});
  final ChecklistController controller;
  final String id;
  @override
  State<ChecklistScreen> createState()=>_ChecklistScreenState();
}
class _ChecklistScreenState extends State<ChecklistScreen> {
  String search='';
  String filter='All';
  ChecklistController get controller=>widget.controller;
  @override
  Widget build(BuildContext context)=>AnimatedBuilder(animation:controller,builder:(context,child) {
    final row=controller.checklists.where((r)=>r['id']==widget.id).firstOrNull;
    if(row==null) { return Scaffold(appBar:AppBar(),body:const Center(child:Text('This checklist was deleted on another device.'))); }
    final displayedRevision=controller.revision;
    final all=controller.tasks(widget.id);
    final completed=all.where((t)=>t['is_completed']==true).length;
    final tasks=all.where((t)=>(('${t['title']} ${t['description']}').toLowerCase().contains(search.toLowerCase())) && (filter=='All' || (filter=='Completed')==(t['is_completed']==true))).toList();
    final bottom=controller.settings['completed_bottom']==true;
    if(bottom) { tasks.sort((a,b) { final order=(a['is_completed']==true?1:0).compareTo(b['is_completed']==true?1:0); return order!=0?order:(a['display_order'] as int).compareTo(b['display_order'] as int); }); }
    final editable=controller.online&&!controller.busy;
    final draggable=editable&&search.isEmpty&&filter=='All'&&!bottom;
    Widget tile(int index) {
      final task=tasks[index];
      return Card(key:ValueKey(task['id']),child:ListTile(
        leading:Checkbox(value:task['is_completed']==true,onChanged:editable?(value)=>action(context,()=>controller.complete(task,value!)):null),
        title:Text(task['title'] as String,style:TextStyle(decoration:task['is_completed']==true?TextDecoration.lineThrough:null)),
        subtitle:Text('${task['priority']}${task['due_date']==null?'':' • Due ${task['due_date']}'}${(task['description'] as String).isEmpty?'':'\n${task['description']}'}'),
        onTap:editable?()=>taskEditor(context,controller,widget.id,row:task):null,
        trailing:PopupMenuButton<String>(enabled:editable,onSelected:(value)=>value=='edit'?taskEditor(context,controller,widget.id,row:task):action(context,() async { if(await confirm(context,controller,'Delete this task permanently?')) { await controller.write('delete_task',{'id':task['id']},expectedRevision:displayedRevision); } }),itemBuilder:(_)=>const [PopupMenuItem(value:'edit',child:Text('Edit')),PopupMenuItem(value:'delete',child:Text('Delete'))]),
      ));
    }
    return Scaffold(appBar:AppBar(title:Text(row['name'] as String),actions:[PopupMenuButton<String>(enabled:editable,onSelected:(value) async {
      if(value=='settings') { await checklistEditor(context,controller,row:row); }
      else if(value=='duplicate') { await action(context,()=>controller.write('duplicate',{'id':widget.id,'new_id':const Uuid().v4()})); }
      else if(value=='delete') { await action(context,() async { if(await confirm(context,controller,'Delete this checklist and all its tasks?')) { await controller.write('delete_checklist',{'id':widget.id},expectedRevision:displayedRevision); if(context.mounted) { Navigator.pop(context); } } }); }
      else if(value=='clear') { await action(context,() async { if(await confirm(context,controller,'Permanently delete currently completed tasks?')) { await controller.write('clear_completed',{'id':widget.id,'period_key':row['period_key']},expectedRevision:displayedRevision); } }); }
    },itemBuilder:(_)=>const [PopupMenuItem(value:'settings',child:Text('Checklist settings')),PopupMenuItem(value:'duplicate',child:Text('Duplicate')),PopupMenuItem(value:'clear',child:Text('Clear completed tasks')),PopupMenuItem(value:'delete',child:Text('Delete checklist'))])]),
    body:Column(children:[SyncBanner(controller:controller),Padding(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text('$completed/${all.length} completed • ${all.length-completed} remaining • ${all.isEmpty?0:(completed*100/all.length).round()}%'),const SizedBox(height:8),LinearProgressIndicator(value:all.isEmpty?0:completed/all.length,borderRadius:BorderRadius.circular(8)),const SizedBox(height:8),Text(resetLabel(row,controller.data['timezone'] as String),style:Theme.of(context).textTheme.bodySmall),const SizedBox(height:16),
      TextField(onChanged:(value)=>setState(()=>search=value),decoration:const InputDecoration(prefixIcon:Icon(Icons.search),labelText:'Search tasks')),
      const SizedBox(height:8),Wrap(spacing:8,children:[for(final value in ['All','Incomplete','Completed']) ChoiceChip(label:Text(value),selected:filter==value,onSelected:(_)=>setState(()=>filter=value))]),
    ])),Expanded(child:draggable?ReorderableListView.builder(padding:const EdgeInsets.fromLTRB(12,0,12,88),itemCount:tasks.length,itemBuilder:(_,index)=>tile(index),onReorder:(oldIndex,newIndex)=>action(context,() async {
      if(newIndex>oldIndex) { newIndex--; }
      tasks.insert(newIndex,tasks.removeAt(oldIndex));
      await controller.write('reorder',{'table':'tasks','checklist_id':widget.id,'ids':tasks.map((t)=>t['id']).toList()},expectedRevision:displayedRevision);
    })):ListView.builder(padding:const EdgeInsets.fromLTRB(12,0,12,88),itemCount:tasks.length,itemBuilder:(_,index)=>tile(index))) ]),
    floatingActionButton:FloatingActionButton(onPressed:editable?()=>taskEditor(context,controller,widget.id):null,tooltip:'Add task',child:const Icon(Icons.add)));
  });
}

Future<void> taskEditor(BuildContext context,ChecklistController controller,String checklist,{Json? row}) async {
  final title=TextEditingController(text:row?['title'] as String? ?? '');
  final description=TextEditingController(text:row?['description'] as String? ?? '');
  final due=TextEditingController(text:row?['due_date'] as String? ?? '');
  var priority=row?['priority'] as String? ?? 'Medium';
  final id=row?['id'] as String? ?? const Uuid().v4();
  var revision=controller.revision;
  var saving=false;
  String? error;
  await showDialog<void>(context:context,barrierDismissible:false,builder:(context)=>StatefulBuilder(builder:(context,setState)=>AlertDialog(title:Text(row==null?'Add task':'Edit task'),content:SizedBox(width:420,child:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,children:[
    TextField(controller:title,maxLength:1000,decoration:const InputDecoration(labelText:'Title')),const SizedBox(height:12),TextField(controller:description,maxLines:3,maxLength:20000,decoration:const InputDecoration(labelText:'Description (optional)')),const SizedBox(height:12),
    DropdownButtonFormField<String>(initialValue:priority,items:[for(final p in ['Low','Medium','High']) DropdownMenuItem(value:p,child:Text(p))],onChanged:saving?null:(value)=>setState(()=>priority=value!),decoration:const InputDecoration(labelText:'Priority')),const SizedBox(height:12),
    TextField(controller:due,decoration:const InputDecoration(labelText:'Due date (YYYY-MM-DD, optional)')),
    if(error!=null) Padding(padding:const EdgeInsets.only(top:12),child:Text(error!)),
  ]))),actions:[TextButton(onPressed:saving?null:()=>Navigator.pop(context),child:const Text('Cancel')),FilledButton(onPressed:saving?null:() async {
    if(title.text.trim().isEmpty) { setState(()=>error='Please enter a title.'); return; }
    final date=due.text.trim();
    if(date.isNotEmpty) {
      final parsed=DateTime.tryParse(date);
      if(!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(date) || parsed==null || parsed.toIso8601String().substring(0,10)!=date) { setState(()=>error='Enter a real date as YYYY-MM-DD, or leave it empty.'); return; }
    }
    setState(()=>saving=true);
    try {
      await controller.write(row==null?'create_task':'edit_task',{'id':id,'checklist_id':checklist,'title':title.text.trim(),'description':description.text,'priority':priority,'due_date':date.isEmpty?null:date},expectedRevision:revision);
      if(context.mounted) { Navigator.pop(context); }
    } catch (_) {
      await controller.refresh();
      revision=controller.revision;
      final latest=controller.tasks(checklist).where((t)=>t['id']==id).firstOrNull;
      if(context.mounted) { setState(()=>error='Save not confirmed or cloud changed. Draft kept. Current cloud task: ${latest?['title'] ?? '(not present)'} / ${latest?['description'] ?? ''}. Review before retrying.'); }
    } finally { if(context.mounted) { setState(()=>saving=false); } }
  },child:const Text('Save'))])));
  title.dispose(); description.dispose(); due.dispose();
}

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key,required this.controller,required this.onLogout});
  final ChecklistController controller;
  final Future<void> Function() onLogout;
  @override
  Widget build(BuildContext context)=>AnimatedBuilder(animation:controller,builder:(context,child)=>Scaffold(appBar:AppBar(title:const Text('Account settings')),body:ListView(children:[
    SyncBanner(controller:controller),
    for(final setting in [('light','Light appearance'),('completed_bottom','Move completed tasks to bottom'),('confirm','Confirm destructive actions')]) SwitchListTile(title:Text(setting.$2),value:controller.settings[setting.$1] as bool? ?? (setting.$1=='confirm'),onChanged:controller.online&&!controller.busy?(value)=>action(context,()=>controller.write('settings',{setting.$1:value})):null),
    ListTile(title:const Text('Account timezone'),subtitle:Text(controller.data['timezone'] as String),trailing:const Icon(Icons.edit_outlined),onTap:controller.online&&!controller.busy?() async {
      final revision=controller.revision;
      final input=TextEditingController(text:controller.data['timezone'] as String);
      final value=await showDialog<String>(context:context,builder:(context)=>AlertDialog(title:const Text('Account timezone'),content:TextField(controller:input,decoration:const InputDecoration(labelText:'IANA name, e.g. Asia/Seoul')),actions:[TextButton(onPressed:()=>Navigator.pop(context),child:const Text('Cancel')),FilledButton(onPressed:()=>Navigator.pop(context,input.text.trim()),child:const Text('Continue'))]));
      input.dispose();
      if(context.mounted && value!=null && value!=controller.data['timezone'] && await confirm(context,controller,'Changing timezone starts fresh recurring periods on every device. Earlier completions stay in history. Continue?')) { if(context.mounted) { await action(context,()=>controller.write('timezone',{'timezone':value},expectedRevision:revision)); } }
    }:null),
    Padding(padding:const EdgeInsets.all(16),child:FilledButton.tonal(onPressed:() async { Navigator.of(context).popUntil((route)=>route.isFirst); await onLogout(); },child:const Text('Sign out'))),
    const Padding(padding:EdgeInsets.all(16),child:Text('Offline mode is read-only. Last downloaded data remains on this device, separated by account. Signing out removes this device’s saved login and hides cached checklists.')),
  ])));
}
