from pathlib import Path
import sys,json,threading,http.server,urllib.parse,mimetypes
import argparse
p=argparse.ArgumentParser(description="Test locally rendered QWRT HTML, never the router")
p.add_argument('--evidence-dir',type=Path,required=True);p.add_argument('--review-dir',type=Path,required=True);p.add_argument('--original-www',type=Path,required=True);p.add_argument('--chrome',type=Path,required=True)
a=p.parse_args();d=a.evidence_dir.resolve()
from playwright.sync_api import sync_playwright
roots=[a.review_dir/'review-only-files/www',a.original_www]
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  path=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip('/')
  if '..' in path.split('/') or '\\' in path:self.send_error(400);return
  p=d/path if path in ['servers-en.html','servers-zh_cn.html','login-en.html','login-zh_cn.html'] else next((r/path for r in roots if (r/path).is_file()),None)
  if p and p.is_file():data=p.read_bytes();ctype=mimetypes.guess_type(str(p))[0] or 'application/octet-stream'
  elif path.startswith('cgi-bin/'):data=b'{}';ctype='application/json'
  else:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type',ctype+'; charset=utf-8' if ctype in ['text/html','text/css','application/javascript'] else ctype);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();url='http://127.0.0.1:'+str(server.server_port);results=[]
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=str(a.chrome),headless=True)
 context=browser.new_context();context.route('**/*',lambda r:r.continue_() if urllib.parse.urlsplit(r.request.url).hostname=='127.0.0.1' else r.abort())
 for lang in ['en','zh_cn']:
  for width,height in [(1440,1080),(390,844)]:
   page=context.new_page();page.set_viewport_size({'width':width,'height':height});errors=[];missing=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:missing.append(r.url) if r.status>=400 else None)
   page.goto(url+'/servers-'+lang+'.html',wait_until='networkidle');page.screenshot(path=str(d/f'servers-{lang}-{width}.png'),full_page=True)
   metrics=page.evaluate('''() => {const s=document.querySelector('select[id$=".auto_update_day_time"]'), c=document.querySelector('input[type=checkbox][id$=".proxy"]');const l=s&&document.querySelector('label[for="'+s.id+'"]');const rect=e=>e?({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}):null;return {legends:[...document.querySelectorAll('legend')].map(e=>e.textContent.trim()),select:rect(s),label:rect(l),proxy_checked:c?c.checked:null,horizontal_overflow:document.documentElement.scrollWidth>innerWidth+2};}''')
   results.append({'lang':lang,'viewport':width,'metrics':metrics,'js_errors':errors,'missing_resources':missing});page.close()
  page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.goto(url+'/login-'+lang+'.html',wait_until='networkidle');page.screenshot(path=str(d/f'login-{lang}.png'));results.append({'page':'login','lang':lang,'password_fields':page.locator('input[type=password]').count(),'js_errors':errors});page.close()
 browser.close()
server.shutdown();(d/'BROWSER-RESULTS.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(results,indent=2,ensure_ascii=False))

for r in results:
 assert not r['js_errors'],r
 if r.get('page')=='login':assert r['password_fields']==1,r;continue
 assert not r['missing_resources'],r
 m=r['metrics'];assert m['proxy_checked'] is False and not m['horizontal_overflow'],r
 expected=['Subscription Update','Node Filters','New Node Defaults','Subscription Actions'] if r['lang']=='en' else ['订阅更新','节点筛选','新节点默认','订阅操作']
 assert m['legends'][:4]==expected,r
 assert m['select'] and m['label'],r
 if r['viewport']==1440:assert abs(m['select']['y']+m['select']['height']/2-m['label']['y']-m['label']['height']/2)<1,r
 else:assert m['select']['y']>=m['label']['y']+m['label']['height'],r
print('PASS original-renderer bilingual browser, default-off and alignment checks')
