const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statuses = {running:'导入中',completed:'已完成',failed:'失败',awaiting_confirmation:'待确认',rolled_back:'已回滚',cleared:'记录已清空'};
const categories = {
  PARSE_FAILED:'解析失败',IMPORT_FAILED:'导入失败',ECT_REFERENCE:'ECT 关联错误',
  ECT_HEADER_MISMATCH:'ECT 文件名校验',MAPPING_ERROR:'管号/坐标映射',
  SUM_WARNING:'SUM 信息校验',MISSING_REPORT:'未报告 ECT',MISSING_REPORT_FILE:'缺失报告',
  DUPLICATE_ACQUISITION:'重复采集',HASH_CONFLICT:'哈希冲突',DUPLICATE_IMPORT:'重复导入',
  BLANK_INDICATION:'三字符待确认',INVALID_SCOPE:'必填信息/管号错误',
  UNIT_OUTAGE_MISMATCH:'机组与大修不一致',FILE_READ_FAILED:'文件读取失败',
  RPT_UNIT_MISMATCH:'RPT 与 SUM 机组冲突',CROSS_GROUP_DUPLICATE:'跨组相同缺陷待复核',
  SET_UNPARSED:'SET 配置未解析',
};
async function request(url, body) {
  const response = await fetch(url, body === undefined ? {} : {
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '本地服务处理失败');
  return data;
}
const grid = (headers, rows) => `<div class="ac-table-wrap"><table><thead><tr>${headers.map(x=>`<th>${escape(x)}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.map(row=>`<tr>${row.map(x=>`<td title="${escape(x)}">${escape(x)}</td>`).join('')}</tr>`).join(''):`<tr><td colspan="${headers.length}" class="ac-empty">当前范围没有记录</td></tr>`}</tbody></table></div>`;
const changeChannel = typeof BroadcastChannel === 'function'
  ? new BroadcastChannel('thimble-local-data-changes')
  : null;
const windowInstanceId = window.__thimbleWindowInstanceId ||= globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random()}`;
const notifyOtherWindows = type => changeChannel?.postMessage({type,sourceId:windowInstanceId,visualizationNotified:true});

export function mountImportQuality(root) {
  const host = document.createElement('details');
  host.className = 'import-quality';
  host.open = true;
  host.innerHTML = `<summary>数据质量与导入审计</summary>
    <div class="iq-toolbar">
      <label>导入批次<select id="iqBatch"><option value="">全部批次</option></select></label>
      <label>异常类型<select id="iqCategory"><option value="">全部类型</option>${Object.entries(categories).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label>
      <button id="iqRefresh" type="button" title="刷新清单" aria-label="刷新清单">&#8635;</button>
      <button id="iqExport" type="button">导出数据与审计清单</button>
      <button id="iqRollback" type="button" disabled>回滚本批次</button>
      <button id="iqRestore" type="button" disabled>恢复本批次</button>
    </div><div id="iqStatus" role="status"></div>
    <div class="iq-tabs" role="tablist" aria-label="审计清单">
      <button type="button" role="tab" data-list="issues" aria-selected="true" class="active">校验问题</button>
      <button type="button" role="tab" data-list="batches" aria-selected="false">导入批次</button>
      <button type="button" role="tab" data-list="artifacts" aria-selected="false">文件校验</button>
      <button type="button" role="tab" data-list="versions" aria-selected="false">报告版本</button>
      <button type="button" role="tab" data-list="reviews" aria-selected="false">跨组复核</button>
    </div><div id="iqRows"></div><div class="iq-pager"><button id="iqPrev" type="button" aria-label="上一页">&#8592;</button><span id="iqPage"></span><button id="iqNext" type="button" aria-label="下一页">&#8594;</button></div>
    <dialog id="iqConfirm"><form method="dialog"><h2>确认批次回滚</h2><p id="iqConfirmText"></p><div><button value="cancel">取消</button><button value="rollback" class="primary">确认回滚</button></div></form></dialog>`;
  root.append(host);
  const $ = id => host.querySelector('#'+id);
  let data = null, reviewData = null, page = 1, list = 'issues', sequence = 0, feedbackRevision = 0, busy = false, fresh = false;
  function payload() {return {batch_id:$('iqBatch').value,category:$('iqCategory').value};}
  function render() {
    if (list==='reviews') {
      const labels={pending:'待复核',representative:'已指定统计代表',keep_all:'已确认保留全部',reset:'已撤销，待复核'};
      const groups=reviewData?.items||[];
      $('iqRows').innerHTML=groups.slice((page-1)*10,page*10).map(g=>`<section class="iq-review" data-group="${g.group_key}">
        <header><strong>${escape(g.outage)} · TH${g.thimble_id} · ${escape(g.analyst)}</strong><span>${labels[g.status]||'待复核'}</span></header>
        <div class="ac-table-wrap"><table><thead><tr><th>统计代表</th><th>记录</th><th>数据组</th><th>位置</th><th>幅值(V)</th><th>相位(°)</th><th>壁厚(%)</th><th>显示</th><th>测量类型</th><th>通道</th><th>来源报告</th></tr></thead>
        <tbody>${g.members.map(r=>`<tr><td><input type="radio" aria-label="选择记录 ${r.id} 为统计代表" name="representative-${g.group_key}" value="${r.id}" ${r.id===g.representative_id?'checked':''}></td>${[r.id,r.calgroup,r.location,r.volts,r.degrees,r.percent,r.indication,r.measurement_type,r.channel,r.report_path].map(x=>`<td title="${escape(x)}">${escape(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
        <div class="iq-review-actions"><input class="iq-review-reason" aria-label="复核依据" placeholder="复核依据" maxlength="1000"><button type="button" data-review="representative">采用所选代表</button><button type="button" data-review="keep_all">保留全部</button><button type="button" data-review="reset" ${g.history.length?'':'disabled'}>撤销复核</button></div>
        ${g.history.length?`<details class="iq-review-history"><summary>复核历史（${g.history.length}）</summary>${grid(['时间','操作人员','决定','代表记录','依据','状态'],g.history.map(r=>[window.formatDateTime?.(r.created_at)||r.created_at,r.operator,labels[r.action],r.representative_id,r.reason,r.active?'当前':'已失效/被替代']))}</details>`:''}
      </section>`).join('')||'<div class="ac-empty">当前范围没有跨数据组相同缺陷</div>';
      const pages=Math.max(1,Math.ceil(groups.length/10));
      $('iqPage').textContent=`${page} / ${pages} · ${groups.length} 组 · ${reviewData?.pending||0} 组待复核`;
      $('iqPrev').disabled=busy||page<=1;$('iqNext').disabled=busy||page>=pages;
      $('iqRows').querySelectorAll('[data-review]').forEach(button=>{button.disabled=!fresh||busy||button.disabled;});
      $('iqRollback').disabled=$('iqRestore').disabled=true;
      return;
    }
    const fields = {
      issues:[['批次','级别','类型','问题','来源文件','工作表','行号','字段'],r=>[r.batch_id,r.severity==='error'?'错误':'提醒',categories[r.code]||r.code,r.message,r.source_path,r.sheet_name,r.row_number,r.field_name]],
      batches:[['批次','时间','操作人员','来源','解析器','状态','解析','入库','重复','错误'],r=>[r.id,window.formatDateTime?.(r.started_at)||r.started_at,r.operator,r.source_path,r.parser_version,statuses[r.status]||r.status,r.rows_parsed,r.rows_inserted,r.rows_skipped,r.error_count]],
      artifacts:[['批次','文件','类型','字节数','SHA-256','解析状态','错误'],r=>[r.batch_id,r.path,r.extension,r.file_size,r.sha256,({parsed:'已解析',parsed_configuration:'配置已解析',archived_unparsed:'已归档，未解析',candidate:'保留候选',failed:'解析失败'})[r.parse_status]||r.parse_status,r.error_message]],
      versions:[['批次','大修','机组','数据组','报告文件','选用','来源路径'],r=>[r.batch_id,r.outage,r.unit_id,r.calgroup,r.filename,r.batch_selected?'本批次选用':'保留候选',r.source_path]],
    };
    const [headers, row] = fields[list];
    $('iqRows').innerHTML = grid(headers,(data?.[list]||[]).map(row));
    const total = list === 'batches' ? data?.batch_total||0 : data?.totals[list]||0;
    const pages = list === 'batches' ? 1 : Math.max(1,Math.ceil(total/50));
    $('iqPage').textContent = `${page} / ${pages} · ${total} 条${list==='batches'&&total>200?'（最近 200 批；完整清单可导出）':''}`;
    $('iqPrev').disabled = busy || page<=1;
    $('iqNext').disabled = busy || page>=pages;
    const batch = data?.batches.find(r=>String(r.id)===$('iqBatch').value);
    $('iqRollback').disabled = !fresh || busy || !batch || batch.status!=='completed' || !batch.rows_parsed;
    $('iqRestore').disabled = !fresh || busy || !batch || batch.status!=='rolled_back';
  }
  async function refresh() {
    const current = ++sequence;
    const feedback = ++feedbackRevision;
    host.setAttribute('aria-busy','true');
    fresh=false;
    host.querySelectorAll('#iqRollback,#iqRestore,[data-review]').forEach(button=>button.disabled=true);
    $('iqStatus').textContent='正在读取本机审计记录...';
    try {
      const result = await request('/api/data-quality?'+new URLSearchParams({...payload(),page,size:50}));
      if (current!==sequence) return;
      data=result;
      if(list==='reviews') {
        const reviews=await request('/api/cross-group-reviews?'+new URLSearchParams({batch_id:$('iqBatch').value}));
        if(current!==sequence)return;
        reviewData=reviews;
      }
      const selected=$('iqBatch').value;
      $('iqBatch').innerHTML='<option value="">全部批次</option>'+data.batches.map(r=>`<option value="${r.id}">#${r.id} · ${escape(window.formatDateTime?.(r.started_at)||r.started_at)} · ${escape(statuses[r.status]||r.status)} · ${escape(r.source_path.split(/[\\/]/).pop())}</option>`).join('');
      $('iqBatch').value=selected;
      fresh=true;
      if(feedback===feedbackRevision)$('iqStatus').textContent=`校验问题 ${data.totals.issues} 项 · 文件 ${data.totals.artifacts} 个${data.legacy_rows?` · ${data.legacy_rows} 条历史记录没有批次信息，无法补推原始导入过程`:''}。导出包含概览、有效检测记录和各类审计清单；异常类型仅筛选校验问题。`;
      render();
      return {ok:true};
    } catch (error) {
      if(current===sequence){if(feedback===feedbackRevision)$('iqStatus').textContent=`审计列表读取失败：${error.message}。请点击刷新后继续操作。`;render();}
      return {ok:false,error:error.message};
    } finally {
      if(current===sequence)host.setAttribute('aria-busy','false');
    }
  }
  async function act(action) {
    const batchId=Number($('iqBatch').value);
    if(!batchId||busy||!fresh)return;
    if(action==='rollback') {
      $('iqConfirmText').textContent=`回滚批次 #${batchId} 的新增记录、三字符修改及该批次自动写入的管状态；原始文件和审计记录保留，可恢复该批次。记录或管状态如有后续修改，将取消操作，不会部分回滚。`;
      const accepted=await new Promise(resolve=>{
        $('iqConfirm').addEventListener('close',()=>resolve($('iqConfirm').returnValue==='rollback'),{once:true});
        $('iqConfirm').showModal();
      });
      if(!accepted)return;
    }
    ++feedbackRevision;busy=true;render();
    try {
      const result=await request('/api/import-batches/action',{batch_id:batchId,action});
      window.dispatchEvent(new Event('workspace-data-changed'));
      notifyOtherWindows('workspace-data-changed');
      window.loadOverview?.().then(()=>window.loadRows?.()).catch(()=>{});
      const refreshed=await refresh();
      $('iqStatus').textContent=`批次 #${batchId} 已${action==='rollback'?'回滚':'恢复'}，涉及 ${result.changed} 条记录`+
        (refreshed?.ok?'':`；审计列表刷新失败：${refreshed?.error||'读取被中断'}。无需重复操作，请点击刷新。`);
    } catch(error) {$('iqStatus').textContent=error.message;}
    finally {busy=false;render();}
  }
  host.addEventListener('toggle',()=>{if(host.open)refresh();});
  $('iqBatch').onchange=$('iqCategory').onchange=()=>{page=1;refresh();};
  $('iqRefresh').onclick=refresh;
  $('iqPrev').onclick=()=>{page--;refresh();};
  $('iqNext').onclick=()=>{page++;refresh();};
  host.querySelectorAll('[data-list]').forEach(button=>button.onclick=()=>{
    list=button.dataset.list;page=1;
    $('iqCategory').disabled=list!=='issues';
    host.querySelectorAll('[data-list]').forEach(tab=>{const active=tab===button;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));});
    refresh();
  });
  $('iqRollback').onclick=()=>act('rollback');
  $('iqRestore').onclick=()=>act('restore');
  $('iqRows').addEventListener('click',async event=>{
    const button=event.target.closest('[data-review]');
    if(!button||busy||!fresh)return;
    const section=button.closest('[data-group]');
    const group=reviewData.items.find(g=>g.group_key===section.dataset.group);
    const selected=section.querySelector('input[type="radio"]:checked');
    if(button.dataset.review==='representative'&&!selected){$('iqStatus').textContent='请先选择一条统计代表记录';return;}
    const body={group_key:group.group_key,revision:group.revision,action:button.dataset.review,
      representative_id:selected?Number(selected.value):null,reason:section.querySelector('.iq-review-reason').value};
    ++feedbackRevision;busy=true;section.querySelectorAll('button,input').forEach(x=>x.disabled=true);
    try {
      await request('/api/cross-group-reviews',body);
      window.dispatchEvent(new Event('cross-group-reviewed'));
      window.dispatchEvent(new Event('workspace-data-changed'));
      notifyOtherWindows('workspace-data-changed');
      const refreshed=await refresh();
      $('iqStatus').textContent=refreshed?.ok
        ?'复核已保存。原始记录完整保留，已通知统计、对比与报告刷新。'
        :`复核已保存；审计列表刷新失败：${refreshed?.error||'读取被中断'}。无需重复保存，请点击刷新。`;
    } catch(error){await refresh();$('iqStatus').textContent=error.message;}
    finally{busy=false;render();}
  });
  $('iqExport').onclick=async()=>{
    $('iqExport').disabled=true;
    ++feedbackRevision;
    $('iqStatus').textContent='正在生成数据与审计清单…';
    try {
      const file=await request('/api/data-quality/export',payload());
      const status=$('iqStatus'),link=document.createElement('a');
      link.href=file.download_url;link.download=file.filename;link.textContent='重新保存';
      let saving=false;
      const save=async()=>{
        if(saving)return;
        saving=true;++feedbackRevision;
        status.textContent='正在保存清单…';
        try {
          const result=await window.saveGeneratedOfficeFile(file);
          const message=result.status==='saved'?'已保存':result.status==='cancelled'?'已取消保存':'已发起下载';
          status.replaceChildren(document.createTextNode(`${message}：${file.finding_rows ?? 0} 条有效检测记录、${file.rows} 项校验问题。 `),link);
        } catch(error) {
          status.replaceChildren(document.createTextNode(`保存失败：${error.message}。 `),link);
        } finally {saving=false;}
      };
      link.onclick=event=>{event.preventDefault();save();};
      await save();
    } catch(error) {$('iqStatus').textContent=error.message;}
    finally {$('iqExport').disabled=false;}
  };
  return host;
}
