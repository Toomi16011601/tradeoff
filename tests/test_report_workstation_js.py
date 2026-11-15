"""Run the offline behavior against a small DOM boundary in Node, without a server."""
import json
import shutil
import subprocess

import pytest

from test_report import Document, report
from tradeoff.report import render_report


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is optional for JS boundary checks')
@pytest.mark.parametrize('price_mode', ['large_integer', 'wide_range'])
def test_recorded_controls_update_exact_values_and_pause_on_manual_or_hidden_selection(price_mode):
    data = report()
    data['economics'] = None
    data['witness']['original_rows'][1].update(open=9007199254740992, high=9007199254740995, low=9007199254740991, close=9007199254740993)
    if price_mode == 'wide_range':
        for index, row in enumerate(data['witness']['original_rows']):
            value = 10 if index % 2 else 1e308
            row.update(open=value, high=value, low=value, close=value)
    data['baseline']['trace'][1]['target'] = 9007199254740992
    data['witness']['mutated_trace'][1]['target'] = 9007199254740993
    doc = Document(render_report(data))
    payload = json.loads(next(value for attrs, value in doc.scripts if attrs.get('id') == 'report-data'))
    nodes = [{'tag': tag, 'attrs': attrs} for tag, attrs in doc.nodes if attrs.get('id')]
    script = next(value for attrs, value in doc.scripts if not attrs.get('id'))
    harness = r'''
const input = JSON.parse(process.argv[1]);
const elements = new Map();
class Node {
  constructor(tag, attrs={}) { this.tag=tag; this.attrs={...attrs}; this.id=attrs.id; this.value=attrs.value || ''; this.disabled='disabled' in attrs; this.textContent=''; this.children=[]; this.events={}; this.dataset={}; for (const [k,v] of Object.entries(attrs)) if(k.startsWith('data-')) this.dataset[k.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=v; this.classList={add(){},remove(){},toggle(){}}; }
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='id'){this.id=v;elements.set(v,this);}}
  getAttribute(k){return this.attrs[k] ?? null;}
  removeAttribute(k){delete this.attrs[k];}
  addEventListener(k,f){(this.events[k] ||= []).push(f);}
  dispatch(k,event={}){for(const f of this.events[k] || [])f({target:this,preventDefault(){},...event});}
  appendChild(n){this.children.push(n);return n;}
  replaceChildren(...nodes){this.children=nodes;}
  get firstChild(){return this.children[0];}
  removeChild(n){this.children=this.children.filter(x=>x!==n);}
  getBoundingClientRect(){return {left:0,width:900};}
  focus(){}
  set innerHTML(_){throw Error('Data must never be HTML');}
}
for(const entry of input.nodes){const n=new Node(entry.tag,entry.attrs);elements.set(n.id,n);}
const scroller=elements.get('trace-plot-scroll');if(scroller){scroller.clientWidth=300;scroller.scrollWidth=900;scroller.scrollLeft=0;}
const source=elements.get('report-data');source.textContent=JSON.stringify(input.payload);
const documentEvents={};const windowEvents={};let serial=0;const timers=new Map();
global.document={getElementById:id=>elements.get(id) || null,querySelectorAll:selector=>selector==='main > section.view'?['overview','evidence','reproducer','method'].map(id=>elements.get(id)):[],documentElement:new Node('html'),createElementNS:(_,tag)=>new Node(tag),createElement:tag=>new Node(tag),addEventListener:(k,f)=>{documentEvents[k]=f;},hidden:false};
global.location={hash:''};global.history={pushState(){}};global.window={addEventListener:(k,f)=>{windowEvents[k]=f;},scrollTo(){},matchMedia:()=>({matches:false,addEventListener(){}})};
global.setInterval=f=>{timers.set(++serial,f);return serial;};global.clearInterval=id=>timers.delete(id);
eval(input.script);
const snapshot=()=>({scrollLeft:elements.get('trace-plot-scroll')?.scrollLeft ?? null,geometry:elements.get('trace-plot').children.length,finiteGeometry:elements.get('trace-plot').children.every(n=>Object.entries(n.attrs).every(([k,v])=>!['x','x1','x2','y','y1','y2','width','height'].includes(k)||Number.isFinite(Number(v)))),original:elements.get('selected-original')?.textContent,intervened:elements.get('selected-intervention')?.textContent,row:elements.get('selected-row')?.textContent,cursor:elements.get('trace-scrubber')?.value,replay:elements.get('trace-replay')?.textContent,pressed:elements.get('trace-replay')?.getAttribute('aria-pressed'),timers:timers.size,ohlcExact:elements.get('selected-ohlc')?.children.map(n=>n.children[1]?.getAttribute('title')),changes:elements.get('bar-change-details')?.children.map(n=>n.textContent || n.children.map(c=>c.textContent).join(' ')).join(' ')});
const out=[snapshot()];
elements.get('trace-next').dispatch('click');out.push(snapshot());
elements.get('changed-row-select').dispatch('click');out.push(snapshot());
elements.get('trace-replay').dispatch('click');out.push(snapshot());
for(const tick of [...timers.values()])tick();out.push(snapshot());
elements.get('witness-select').dispatch('click');out.push(snapshot());
elements.get('trace-replay').dispatch('click');location.hash='#evidence';windowEvents.hashchange();out.push(snapshot());
console.log(JSON.stringify(out));
'''
    result = subprocess.run(['node', '-e', harness, json.dumps({'payload': payload, 'nodes': nodes, 'script': script})], text=True, capture_output=True, check=True)
    states = json.loads(result.stdout)
    assert states[0]['original'] == '9007199254740992'
    assert states[0]['intervened'] == '9007199254740993'
    assert states[0]['ohlcExact'] == (['9007199254740992','9007199254740995','9007199254740991','9007199254740993'] if price_mode == 'large_integer' else ['10'] * 4)
    assert states[0]['timers'] == 0, 'Recorded playback must not autoplay'
    assert states[1]['cursor'] == '2'
    assert (states[1]['original'], states[1]['intervened']) == ('0', '0')
    assert states[2]['cursor'] == '3' and states[2]['row'] == '3'
    assert states[2]['scrollLeft'] == 600, 'Changed selection must remain in the bounded chart viewport'
    assert 'open' in states[2]['changes'] and '10' in states[2]['changes'] and '100' in states[2]['changes']
    assert states[3]['pressed'] == 'true' and states[3]['timers'] == 1
    assert states[4]['cursor'] == '1'
    assert states[5]['cursor'] == '1' and states[5]['timers'] == 0
    assert states[5]['geometry'] > 0 and states[5]['finiteGeometry']
    assert states[6]['pressed'] == 'false' and states[6]['timers'] == 0


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is optional for JS boundary checks')
def test_full_tape_bounds_do_not_depend_on_javascript_argument_count():
    """150k recorded points exceed spread-argument limits in Node and browsers."""
    script = next(value for attrs, value in Document(render_report(report())).scripts if not attrs.get('id'))
    harness = r'''
const script = process.argv[1];
const count=150000, nodes=new Map();let focus;
const make=()=>({value:'0',dataset:{},textContent:'',setAttribute(){},replaceChildren(){},appendChild(){},addEventListener(){},classList:{add(){}}});
for(const id of ['report-data','trace-scrubber','temporal-chart','trace-plot','witness-select'])nodes.set(id,make());
nodes.get('witness-select').addEventListener=(_,fn)=>{focus=fn;};
const bars=Array.from({length:count},(_,i)=>({timestamp:'2026-01-01T00:00:00+00:00',time_ms:i*1000,original_target:String(i%2),intervention_target:null,ohlc:null,available_at:null,unavailable:null,changed:false,changes:[]}));
nodes.get('report-data').textContent=JSON.stringify({schema_version:'edgelab.audit.v1',workstation:{bars,focus_start:0,focus_end:count-1,initial_index:0,decision_index:0,cutoff_index:null,cutoff_ms:null,changed_indices:[],has_prices:false,price_exact_scale:true,exact_scale:true}});
global.document={getElementById:id=>nodes.get(id)||null,querySelectorAll:()=>[],documentElement:make(),createElementNS:()=>make(),createElement:()=>make(),addEventListener(){}};
global.window={addEventListener(){},scrollTo(){}};global.location={hash:''};
eval(script);focus();console.log('rendered');
'''
    result = subprocess.run(['node', '-e', harness, script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'rendered'


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is optional for JS boundary checks')
@pytest.mark.parametrize('direct_fragment', [False, True])
def test_saved_fixture_route_opens_and_scrolls_evidence_without_resetting_to_page_top(direct_fragment):
    script = next(value for attrs, value in Document(render_report(report())).scripts if not attrs.get('id'))
    harness = r'''
const script=process.argv[1], direct=process.argv[2]==='true', scrolls=[], focused=[], events={};let click;
const views=['overview','evidence','reproducer','method'].map(id=>({id,hidden:false}));
const summary={focus(options){focused.push(['summary',options.preventScroll]);}};
const details={open:false,scrollIntoView(options){scrolls.push(['fixture',options.block]);},querySelector:selector=>selector==='summary'?summary:null};
const link={addEventListener(event,handler){if(event==='click')click=handler;}};
const source={textContent:JSON.stringify({schema_version:'edgelab.audit.v1'})};
global.location={hash:direct?'#saved-fixture':''};
global.history={pushState(_,__,fragment){location.hash=fragment;}};
global.document={getElementById:id=>id==='report-data'?source:id==='saved-fixture'?details:null,querySelectorAll:selector=>selector==='main > section.view'?views:selector==='a.summary-repair'?[link]:[],documentElement:{classList:{add(){}}}};
global.window={scrollTo(x,y){scrolls.push(['top',x,y]);},addEventListener(event,handler){events[event]=handler;}};
eval(script);
if(!direct){location.hash='#saved-fixture';events.hashchange();}
const first={open:details.open,scrolls:[...scrolls],focused:[...focused],view:views.filter(v=>!v.hidden).map(v=>v.id)};
details.open=false;scrolls.length=0;focused.length=0;click({preventDefault(){}});
const repeated={open:details.open,scrolls:[...scrolls],focused:[...focused],view:views.filter(v=>!v.hidden).map(v=>v.id)};
scrolls.length=0;focused.length=0;location.hash='#evidence';events.hashchange();
console.log(JSON.stringify({first,repeated,normal:{scrolls,focused,view:views.filter(v=>!v.hidden).map(v=>v.id)}}));
'''
    result = subprocess.run(['node', '-e', harness, script, json.dumps(direct_fragment)], text=True, capture_output=True, check=True)
    actual = json.loads(result.stdout)
    for navigation in [actual['first'], actual['repeated']]:
        assert navigation['open'] is True
        assert navigation['view'] == ['overview']
        assert navigation['scrolls'] == [['fixture', 'start']]
        assert navigation['focused'] == [['summary', True]]
    assert actual['normal'] == {'scrolls': [['top', 0, 0]], 'focused': [], 'view': ['evidence']}
