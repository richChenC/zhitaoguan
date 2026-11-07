import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const outputPath=path.resolve(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp','release-check'),new Date().toISOString().replace(/[:.]/g,'-'));
const tempRoot=path.resolve(process.env.THIMBLE_TEST_TEMP_ROOT||outputPath);
fs.mkdirSync(outputPath,{recursive:true});
fs.mkdirSync(tempRoot,{recursive:true});
const output=fs.realpathSync(outputPath);
const temp=fs.realpathSync(tempRoot);
const python=path.join(root,'.venv','Scripts','python.exe');
const databasePattern=/\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal))?$/i;
function removeTestDatabases(directory){
  if(!fs.existsSync(directory))return;
  for(const entry of fs.readdirSync(directory,{withFileTypes:true})){
    const target=path.join(directory,entry.name);
    if(entry.isSymbolicLink())continue;
    if(entry.isDirectory())removeTestDatabases(target);
    else if(entry.isFile()&&databasePattern.test(entry.name))fs.rmSync(target,{force:true});
  }
}
const units=['window_close_guard_unit.cjs','window_loading_unit.cjs','task_progress_unit.mjs','report_scope_unit.mjs','report_draft_unit.mjs','reference-defect-unit.mjs','defect_axis_verify.mjs','defect_location_verify.mjs','visualization_model_verify.mjs','status_change_model_verify.mjs','tube_history_view_unit.mjs'];
units.push('artifact_save_unit.cjs','download_feedback_unit.cjs','offline_policy_unit.cjs','service_diagnostics_unit.cjs');
const desktop=['desktop_service_isolation.mjs','settings_window_desktop.mjs','settings_workspace_desktop.mjs','release_lifecycle_desktop.mjs','workbench_display_desktop.mjs','selection_export_desktop.mjs','unified_ledger_desktop.mjs','state_batch_desktop.mjs','state_maintenance_desktop.mjs','state_large_import_desktop.mjs','import_progress_desktop.mjs','import_outcome_desktop.mjs','import_wizard_verify.mjs','notification_modal_desktop.mjs','window_size_desktop.mjs','night_mode_workspace_desktop.mjs','night_mode_dialogs_desktop.mjs','status_change_desktop.mjs','plate_scope_desktop.mjs','visualization_analysis_desktop.mjs','visualization_history_desktop.mjs','visualization_workspace_desktop.mjs','reference_model_desktop.mjs','reference_model_real_data.mjs','reference_scope_plate_desktop.mjs','reference_double_click_desktop.mjs'];
desktop.push('visualization_windows_desktop.mjs','import_recovery_desktop.mjs','workspace_usability_desktop.mjs','workspace_edge_cases_desktop.mjs','settings_linkage_desktop.mjs','local_enterprise_desktop.mjs','control_alignment_desktop.mjs');
desktop.push('visualization_accuracy_desktop.mjs');
desktop.push('matched_increments_desktop.mjs');
desktop.push('position_resolution_desktop.mjs');
desktop.push('information_hierarchy_desktop.mjs');
desktop.push('workspace_refinement_desktop.mjs');
desktop.push('report_draft_desktop.mjs','report_layout_desktop.mjs');
desktop.push('professional_ui_desktop.mjs','visualization_controls_desktop.mjs');
desktop.push('cross_group_desktop_verify.mjs');
desktop.push('deletion_refresh_desktop.mjs');
desktop.push('native_export_desktop.mjs');
desktop.push('backup_recovery_desktop.mjs');
desktop.push('finding_edit_refresh_desktop.mjs');
desktop.push('clear_refresh_desktop.mjs');
desktop.push('state_model_sync_desktop.mjs');
desktop.push('remote_data_refresh_desktop.mjs');
const selected=process.argv.find(arg=>arg.startsWith('--only='))?.slice(7).split(',').filter(Boolean);
const group=process.argv.find(arg=>arg.startsWith('--group='))?.slice(8)||'all';
const desktopJobs=[...desktop,'rpt_folder_regression.mjs'];
const jobs=[{name:'source-audit',command:process.execPath,args:['scripts/source-audit.mjs'],group:'unit'},{name:'cleanup-policy',command:'powershell',args:['-NoProfile','-ExecutionPolicy','Bypass','-File','tests/cleanup_policy_verify.ps1'],group:'unit'},...units.map(name=>({name,command:process.execPath,args:['tests/'+name],group:'unit'})),{name:'python-unittest',command:python,args:['-m','unittest','discover','-s','tests','-v'],group:'python'},...desktopJobs.map(name=>({name,command:process.execPath,args:['tests/'+name],group:'desktop'}))].filter(job=>(group==='all'||job.group===group)&&(!selected||selected.includes(job.name.replace(/\.mjs$/,''))));
if(!jobs.length)throw new Error('No matching release checks');
const packagedExecutable=process.env.THIMBLE_TEST_EXECUTABLE;
const packagedChecks=new Set([
  'settings_window_desktop.mjs',
  'workspace_refinement_desktop.mjs','professional_ui_desktop.mjs',
  'position_resolution_desktop.mjs','information_hierarchy_desktop.mjs','workspace_edge_cases_desktop.mjs',
  'visualization_history_desktop.mjs','visualization_analysis_desktop.mjs','visualization_workspace_desktop.mjs',
  'selection_export_desktop.mjs','workbench_display_desktop.mjs',
  'state_batch_desktop.mjs','state_large_import_desktop.mjs','window_size_desktop.mjs',
  'night_mode_workspace_desktop.mjs','night_mode_dialogs_desktop.mjs',
  'reference_model_real_data.mjs','reference_double_click_desktop.mjs','reference_scope_plate_desktop.mjs',
  'report_draft_desktop.mjs','report_layout_desktop.mjs',
  'settings_workspace_desktop.mjs',
  'unified_ledger_desktop.mjs',
  'release_lifecycle_desktop.mjs','state_maintenance_desktop.mjs','settings_linkage_desktop.mjs',
  'visualization_accuracy_desktop.mjs','local_enterprise_desktop.mjs','notification_modal_desktop.mjs',
  'visualization_windows_desktop.mjs','control_alignment_desktop.mjs','visualization_controls_desktop.mjs',
  'cross_group_desktop_verify.mjs','status_change_desktop.mjs',
  'deletion_refresh_desktop.mjs',
  'native_export_desktop.mjs',
  'backup_recovery_desktop.mjs',
  'import_wizard_verify.mjs',
  'finding_edit_refresh_desktop.mjs',
  'clear_refresh_desktop.mjs',
  'state_model_sync_desktop.mjs',
]);
if(packagedExecutable){
  if(!fs.existsSync(packagedExecutable))throw new Error('Packaged executable does not exist: '+packagedExecutable);
  const unsupported=jobs.filter(job=>job.group==='desktop'&&!packagedChecks.has(job.name));
  if(unsupported.length)throw new Error('These checks do not support packaged execution; refusing to substitute development Electron: '+unsupported.map(job=>job.name).join(', '));
}
if(jobs.some(job=>job.group==='desktop'))createRequire(import.meta.url)('electron');
const results=[];
console.log('Release evidence: '+output);
for(const job of jobs){
  const start=Date.now(),file=path.join(output,job.name+'.log'),log=fs.openSync(file,'w');
  const jobTemp=path.join(temp,job.name.replace(/[^a-z0-9_.-]/gi,'_'));
  fs.mkdirSync(jobTemp,{recursive:true});
  console.log('RUN '+job.name);
  const result=await new Promise(resolve=>{
    const sourceDatabase=process.env.THIMBLE_TEST_SOURCE_DB||(job.name==='position_resolution_desktop.mjs'
      ?path.join(root,'.user-data','data','thimble.db'):path.join(root,'data','thimble.db'));
    const child=spawn(job.command,job.args,{cwd:root,windowsHide:true,stdio:['ignore',log,log],env:{...process.env,
      ...(packagedExecutable&&job.name==='local_enterprise_desktop.mjs'?{THIMBLE_TEST_EXE:packagedExecutable}:{}),
      TEMP:jobTemp,TMP:jobTemp,THIMBLE_TEST_TEMP_ROOT:jobTemp,THIMBLE_TEST_OUTPUT_ROOT:output,THIMBLE_TEST_SOURCE_DB:sourceDatabase,PYTHONIOENCODING:'utf-8'}});
    let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;if(process.platform==='win32')spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});else child.kill('SIGKILL');},job.group==='python'?900000:['window_size_desktop.mjs','reference_model_desktop.mjs','reference_scope_plate_desktop.mjs'].includes(job.name)?600000:240000);
    child.once('error',error=>{clearTimeout(timer);resolve({status:'failed',error:error.message});});
    child.once('exit',(code,signal)=>{clearTimeout(timer);resolve({status:timedOut?'timeout':code===0?'passed':'failed',code,signal});});
  });
  fs.closeSync(log);
  removeTestDatabases(output);
  if(jobTemp!==output&&jobTemp.startsWith(temp+path.sep)&&fs.existsSync(jobTemp)){
    fs.rmSync(jobTemp,{recursive:true,force:true});
  }
  results.push({name:job.name,...result,seconds:Math.round((Date.now()-start)/100)/10,log:file,
    runtime:job.group==='desktop'?(packagedExecutable?'packaged':'source'):job.group,
    ...(packagedExecutable&&job.group==='desktop'?{executable:path.resolve(packagedExecutable)}:{})});
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({output,results},null,2));
  console.log(result.status.toUpperCase()+' '+job.name+' '+results.at(-1).seconds+'s');
  if(result.status!=='passed')console.log(fs.readFileSync(file,'utf8').slice(-4500));
}
const failed=results.filter(result=>result.status!=='passed');
console.log(JSON.stringify({passed:results.length-failed.length,failed:failed.length,output}));
process.exitCode=failed.length?1:0;
