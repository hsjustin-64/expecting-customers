// A form-based menu/ingredient editor shared by local and account editions.
function mountShopEditor(){
 const host=document.createElement('div');host.className='panel';
  $('#view .title-row').insertAdjacentElement('afterend',host);
 let draft=structuredClone(state.config);
 function capture(){
  host.querySelectorAll('[data-collection]').forEach(el=>{draft[el.dataset.collection][Number(el.dataset.row)][el.dataset.field]=el.type==='number'?Number(el.value):el.value;});
  host.querySelectorAll('[data-recipe]').forEach(el=>{const item=draft.items[Number(el.dataset.recipe)].id,mat=draft.materials[Number(el.dataset.mat)].id;draft.recipes[item]??={};if(Number(el.value)>0)draft.recipes[item][mat]=Number(el.value);else delete draft.recipes[item][mat];});
 }
 function field(collection,n,key,value,type='text'){
  return `<input aria-label="${esc(collection+' '+(n+1)+' '+key)}" data-collection="${collection}" data-row="${n}" data-field="${key}" type="${type}" value="${esc(value)}" ${type==='number'?'min="0" step="any"':''} required>`;
 }
 function paint(){
  host.innerHTML=`<h2>우리 메뉴 · 재료 등록</h2><p>샘플 메뉴를 우리 가게 메뉴로 바꾸세요. 메뉴 ID는 판매 CSV의 item_id와 같아야 합니다. 저장한 ID는 판매 기록을 연결하는 기준으로 유지됩니다.</p><form id="shopEditorForm"><h3>메뉴</h3>${table(['메뉴 ID','메뉴 이름','가격 (원)','여유 수량',''],draft.items.map((it,n)=>`<tr><td>${esc(it.id)}</td><td>${field('items',n,'name',it.name)}</td><td>${field('items',n,'price',it.price,'number')}</td><td>${field('items',n,'buffer',it.buffer,'number')}</td><td><button type="button" data-remove-item="${n}">삭제</button></td></tr>`))}<button type="button" id="addShopItem">+ 메뉴 추가</button><h3 style="margin-top:24px">재료</h3><p>단위 예: g, mL, 개. 재고·입고량은 재고 화면에서 입력합니다.</p>${table(['재료 이름','단위','주문 묶음 크기','단위당 원가','납기 (일)','발주 마감',''],draft.materials.map((m,n)=>`<tr><td>${field('materials',n,'name',m.name)}</td><td>${field('materials',n,'unit',m.unit)}</td><td>${field('materials',n,'pack_size',m.pack_size,'number')}</td><td>${field('materials',n,'unit_cost',m.unit_cost,'number')}</td><td>${field('materials',n,'lead_time_days',m.lead_time_days,'number')}</td><td>${field('materials',n,'cutoff',m.cutoff,'time')}</td><td><button type="button" data-remove-mat="${n}">삭제</button></td></tr>`))}<button type="button" id="addShopMaterial">+ 재료 추가</button><h3 style="margin-top:24px">메뉴 1개당 재료 사용량</h3><p>사용하지 않는 재료는 0으로 두세요. 각 메뉴에 최소 한 재료가 필요합니다.</p>${table(['메뉴',...draft.materials.map(m=>esc(m.name)+' ('+esc(m.unit)+')')],draft.items.map((it,n)=>`<tr><td>${esc(it.name)}</td>${draft.materials.map((m,j)=>`<td><input type="number" min="0" step="any" required aria-label="${esc(it.name+' '+m.name+' 사용량')}" data-recipe="${n}" data-mat="${j}" value="${draft.recipes[it.id]?.[m.id]??0}"></td>`).join('')}</tr>`))}<button class="primary" style="margin-top:20px">메뉴 · 재료 · 레시피 저장</button></form>`;
  $('#addShopItem').onclick=()=>{capture();const id=prompt('판매 CSV에 사용할 메뉴 ID를 입력하세요. 예: americano');if(!id)return;if(draft.items.some(i=>i.id===id.trim())){msg('이미 있는 메뉴 ID입니다.',true);return;}draft.items.push({id:id.trim(),name:'새 메뉴',price:0,buffer:0});draft.recipes[id.trim()]={};paint();};
  $('#addShopMaterial').onclick=()=>{capture();const id='material_'+Date.now();draft.materials.push({id,name:'새 재료',unit:'g',stock:0,remaining_today:0,expiry_date:state.tomorrow,incoming_qty:0,incoming_date:state.tomorrow,incoming_expiry:state.tomorrow,pack_size:1,unit_cost:0,lead_time_days:1,cutoff:'15:00'});paint();};
  host.querySelectorAll('[data-remove-item]').forEach(b=>b.onclick=()=>{capture();const [it]=draft.items.splice(Number(b.dataset.removeItem),1);delete draft.recipes[it.id];paint();});
  host.querySelectorAll('[data-remove-mat]').forEach(b=>b.onclick=()=>{capture();const [m]=draft.materials.splice(Number(b.dataset.removeMat),1);for(const rec of Object.values(draft.recipes))delete rec[m.id];paint();});
  $('#shopEditorForm').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{capture();await api('config',draft);await reload();msg('우리 매장의 메뉴와 재료를 저장했습니다. 판매 이력과 실제 재고를 입력하세요.');});};
 }
 paint();
}
