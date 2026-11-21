const notice=document.getElementById('notice');
function postJSON(path,data){
  notice.textContent='处理中…';
  return fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
    .then(async r=>{const body=await r.json();if(!r.ok)throw new Error(body.message);window.location.reload();})
    .catch(e=>{notice.textContent=e.message;});
}
document.getElementById('calculate')?.addEventListener('click',()=>
  postJSON('/api/coverage',{sample:document.getElementById('dataset').value}));
document.getElementById('export-coverage')?.addEventListener('click',async()=>{
  const id=document.getElementById('coverage-data')?.dataset.evidence;
  if(!id){notice.textContent='未找到证据批次。';return;}
  const r=await fetch('/api/coverage/'+id+'/archive');
  const body=await r.json();
  if(!r.ok){notice.textContent='导出失败。';return;}
  const blob=new Blob([body.csv],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download='coverage_'+id+'.csv';a.click();URL.revokeObjectURL(a.href);
});
document.getElementById('attach')?.addEventListener('click',async()=>{
  const file=document.getElementById('attachment').files[0];
  if(!file){notice.textContent='请选择证据文件。';return;}
  const form=new FormData();form.append('file',file);
  notice.textContent='导入中…';
  try{
    const r=await fetch('/api/coverage/upload',{method:'POST',body:form});
    const body=await r.json();if(!r.ok)throw Error(body.message);location.reload();
  }catch(e){notice.textContent=e.message;}
});
document.getElementById('batch-select')?.addEventListener('change',function(){
  window.location.href='/coverage?evidence='+this.value;
});
document.getElementById('publish-cert')?.addEventListener('click',()=>{
  const node=document.getElementById('coverage-data');
  if(!node){notice.textContent='请先生成计量批次。';return;}
  return postJSON('/api/runs/'+node.dataset.run+'/certificate/publish',{evidence_id:node.dataset.evidence});
});
