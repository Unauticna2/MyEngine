// Isolated browser API fixture: submits are intercepted, no money is sent.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { webcrypto } = require('node:crypto');
const source = fs.readFileSync(require('node:path').join(__dirname,'../templates/payment-site/app.js'),'utf8');
function run({query='', amount='12.50', product='gold', enabled=true, protocol='https:', stored=null}={}) {
  const elements={};
  const el=id=>elements[id] ||= {value:'',textContent:'',hidden:id==='return-panel',disabled:false,handlers:{},
    addEventListener(t,f){this.handlers[t]=f},setCustomValidity(x){this.validity=x},focus(){}};
  const location=new URL(protocol+'//example.invalid/shop/'+query);
  const config={receiver:'41001234567890',supportUrl:'mailto:demo@example.invalid',activationText:'Проверка вручную.',paymentsEnabled:enabled,amount,productId:product};
  const key='myengine.payment.pending.v2.'+config.receiver+'.'+product;
  const memory=new Map(stored?[[key,JSON.stringify(stored)]]:[]);
  const form=el('payment-form');let sent=0;let method={value:'PC'};
  form.querySelector=s=>s.includes('quickpay-form')?{value:'button'}:method;
  form.reportValidity=()=>!el('player-id').validity&&el('consent').checked;
  function HTMLFormElement(){};HTMLFormElement.prototype.submit=function(){sent++};
  const events={};
  vm.runInNewContext(source,{window:{MYENGINE_CONFIG:config,location,crypto:webcrypto,addEventListener:(t,f)=>events[t]=f},
    document:{getElementById:el,querySelectorAll:()=>[]},URL,Uint32Array,Date,HTMLFormElement,
    sessionStorage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)}});
  return {el,key,memory,form,events,sent:()=>sent,setMethod:v=>method=v,
    submit(id='player_01',consent=true){el('player-id').value=id;el('consent').checked=consent;form.handlers.submit({preventDefault(){}})}};
}
let count=0;function test(name,fn){fn();count++;console.log('OK '+name)}
test('custom configured price and receiver override URL tampering',()=>{
  const r=run({query:'?product=gold&amount=0&receiver=other&paid=true'});r.submit();
  assert.equal(r.sent(),1);assert.equal(r.el('sum').value,'12.50');assert.equal(r.el('receiver').value,'41001234567890');
  assert.equal(r.form.action,'https://yoomoney.ru/quickpay/confirm');assert.equal(r.el('return-panel').hidden,true);
  assert.equal(new URL(r.el('success-url').value).searchParams.get('product'),'gold');
});
test('product mismatch cannot submit',()=>{const r=run({query:'?product=other'});r.submit();assert.equal(r.sent(),0);assert.match(r.el('form-message').textContent,/не совпадает/)});
test('engine request ID becomes the payment label',()=>{const r=run({query:'?product=gold&requestId='+'a'.repeat(32)});r.submit();assert.equal(r.el('payment-label').value,'ME-'+'a'.repeat(32));assert.equal(JSON.parse(r.memory.get(r.key)).player,'player_01')});
test('malformed request ID uses a new label',()=>{const r=run({query:'?requestId=bad<script>'});r.submit();assert.match(r.el('payment-label').value,/^DLX-player_01-/)});
test('double click submits once',()=>{const r=run();r.submit();r.submit();assert.equal(r.sent(),1)});
test('zero negative fractional and nonfinite prices are blocked',()=>{for(const amount of ['0.00','-1.00','1.001','NaN','Infinity','1000001.00']){const r=run({amount});r.submit();assert.equal(r.sent(),0)}});
test('local preview and disabled payment never submit',()=>{for(const options of [{protocol:'file:'},{enabled:false}]){const r=run(options);r.submit();assert.equal(r.sent(),0)}});
test('invalid player consent and payment method block transfer',()=>{
  let r=run();r.submit('bad id');assert.equal(r.sent(),0);
  r=run();r.submit('valid',false);assert.equal(r.sent(),0);
  r=run();r.setMethod({value:'EVIL'});r.submit();assert.equal(r.sent(),0);
});
test('return restores manual instructions and engine label',()=>{const r=run({query:'?payment=returned&product=gold',stored:{player:'tester',label:'ME-'+'a'.repeat(32),product:'gold',createdAt:Date.now()}});assert.equal(r.sent(),0);assert.match(r.el('return-order').textContent,/tester/);assert.equal(r.el('player-id').value,'tester')});
test('return ignores another product record',()=>{const r=run({query:'?payment=returned',stored:{player:'tester',label:'ME-'+'a'.repeat(32),product:'other',createdAt:Date.now()}});assert.equal(r.el('player-id').value,'');assert.equal(r.sent(),0)});
test('safe player prefill is optional',()=>{assert.equal(run({query:'?playerId=test_01'}).el('player-id').value,'test_01');assert.equal(run({query:'?playerId=%3Cscript%3E'}).el('player-id').value,'')});
console.log(`${count} checkout checks passed; no network requests.`);
