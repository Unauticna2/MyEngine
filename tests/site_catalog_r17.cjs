// Runs the exported site's actual config/app/developer code. Network and submits are intercepted.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const root=process.argv[2];if(!root)throw Error('Pass the generated site directory');
const loaded={window:{}};vm.runInNewContext(fs.readFileSync(path.join(root,'config.js'),'utf8'),loaded);
const original=JSON.parse(JSON.stringify(loaded.window.MYENGINE_CONFIG));
const source=fs.readFileSync(path.join(root,'app.js'),'utf8');
const developerSource=fs.readFileSync(path.join(root,'developer.js'),'utf8');
const api=require(path.join(root,'developer-core.js'));
function run(query='',override={},memory=new Map()){
  const config={...structuredClone(original),...override},elements={};
  const el=id=>elements[id]||=( {value:'',hidden:['developer-access','developer-result','return-panel'].includes(id),textContent:'',handlers:{},
    addEventListener(t,f){this.handlers[t]=f},setCustomValidity(v){this.validity=v},focus(){},setAttribute(k,v){this[k]=v}} );
  const fields=['title','price','description','id'].map(key=>Object.assign(el('display-'+key),{dataset:{productField:key}}));
  const links=(Array.isArray(config.products)?config.products:[]).map((p,i)=>Object.assign(el('link-'+i),{dataset:{catalogProduct:p.productId}}));
  let sent=0,issued=null;const events={};
  const form=el('payment-form');form.reportValidity=()=>!el('player-id').validity&&el('consent').checked;
  form.querySelector=q=>q.includes('quickpay-form')?{value:'button'}:{value:'PC'};
  el('developer-form').reportValidity=()=>true;
  function HTMLFormElement(){};HTMLFormElement.prototype.submit=function(){sent++};
  const ctx={window:{MYENGINE_CONFIG:config,location:new URL('https://example.invalid/store/'+query),crypto:webcrypto,
    addEventListener:(t,f)=>events[t]=f,MyEngineDeveloper:{...api,issue:async(...args)=>(issued=await api.issue(...args))}},
    document:{getElementById:el,querySelectorAll:s=>s==='[data-product-field]'?fields:s==='[data-catalog-product]'?links:[]},
    URL,Uint32Array,Date,HTMLFormElement,sessionStorage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)}};
  vm.createContext(ctx);vm.runInContext(source,ctx);vm.runInContext(developerSource,ctx);
  return {el,links,ctx,memory,config,sent:()=>sent,issued:()=>issued,
    submit(id='player_01'){el('player-id').value=id;el('consent').checked=true;form.handlers.submit({preventDefault(){}})}};
}
let count=0;async function test(name,fn){await fn();count++;console.log('OK '+name)}
(async()=>{
  await test('every product controls its amount title description and activation',()=>{
    for(const item of original.products){const r=run('?product='+item.productId+'&amount=0&receiver=bad');r.submit();
      assert.equal(r.sent(),1);assert.equal(r.el('sum').value,item.amount);assert.equal(r.el('receiver').value,original.receiver);
      assert.equal(r.el('display-title').textContent,item.productTitle);assert.equal(r.el('display-description').textContent,item.description);
      assert.equal(r.el('activation-text').textContent,item.activationText);assert.equal(r.ctx.window.MyEngineStore.selected.productId,item.productId);
      assert.equal(r.links.find(l=>l.dataset.catalogProduct===item.productId)['aria-current'],'true');
      assert.equal(new URL(r.el('success-url').value).searchParams.get('product'),item.productId);
      assert.ok(r.el('payment-label').value.startsWith('MP-'+item.paymentCode+'-'));
    }
  });
  await test('without query first product is selected',()=>{const r=run();r.submit();assert.equal(r.el('sum').value,original.products[0].amount)});
  await test('unknown product blocks transfer and developer certificate',()=>{const r=run('?product=missing');r.submit();assert.equal(r.sent(),0);assert.equal(r.ctx.window.MyEngineStore.selected,null);assert.equal(r.el('developer-access').hidden,true)});
  await test('engine label contains selected product code and request ID',()=>{const item=original.products[1],nonce='a'.repeat(32);const r=run('?product='+item.productId+'&requestId='+nonce);r.submit();assert.equal(r.el('payment-label').value,`ME-${item.paymentCode}-${nonce}`)});
  await test('a request ID without a product is not reused',()=>{const r=run('?requestId='+'a'.repeat(32));r.submit();assert.match(r.el('payment-label').value,/^MP-/)});
  await test('switching products discards the old order but keeps valid player ID',()=>{
    const r=run('?product=game&requestId='+'a'.repeat(32)+'&payment=returned');r.el('player-id').value='player_01';
    const link=r.links[1];link.handlers.click();const url=new URL(link.href);
    assert.equal(url.searchParams.get('product'),'dlc1');assert.equal(url.searchParams.get('requestId'),null);assert.equal(url.searchParams.get('payment'),null);assert.equal(url.searchParams.get('playerId'),'player_01');
    const next=run(url.search);next.submit();assert.match(next.el('payment-label').value,/^MP-/);
  });
  await test('return instructions stay separate for two different products',()=>{
    const memory=new Map();for(const item of original.products.slice(0,2)){const r=run('?product='+item.productId,{},memory);r.submit('player_'+item.productId)}
    for(const item of original.products.slice(0,2)){const r=run('?product='+item.productId+'&payment=returned',{},memory);assert.equal(r.el('player-id').value,'player_'+item.productId);assert.match(r.el('return-order').textContent,new RegExp(item.productId));assert.equal(r.sent(),0)}
  });
  await test('long product and player IDs fit the label limit',()=>{
    const product={...original.products[0],productId:'x'.repeat(100)};const r=run('?product='+product.productId,{products:[product]});r.submit('a'.repeat(32));assert.equal(r.sent(),1);assert.ok(r.el('payment-label').value.length<=64);
  });
  await test('duplicate IDs or malformed catalog fail closed',()=>{
    for(const products of [[],{},[original.products[0],original.products[0]],[{...original.products[0],amount:'-1.00'}]]){
      const r=run('',{products});r.submit();assert.equal(r.sent(),0);
    }
  });
  await test('developer certificate identifies the selected DLC',async()=>{
    const settings=await api.createSettings('author','1234','+79000000000');
    const r=run('?product=dlc1',{developerAccess:settings});
    assert.equal(r.el('developer-access').hidden,false);
    r.el('developer-player').value='author';r.el('developer-last4').value='1234';r.el('developer-phone').value='+79000000000';
    await r.el('developer-form').handlers.submit({preventDefault(){}});
    assert.equal(r.issued().productId,'dlc1');assert.equal(r.issued().edition,original.products[1].productTitle);
    assert.equal(r.issued().payment.status,'not_required');assert.equal(r.issued().payment.amount,0);
  });
  console.log(`${count} catalog checks passed; no real payments.`);
})().catch(error=>{console.error(error);process.exitCode=1});
