"""Microsoft-backed local service and setup API."""
import json
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from .microsoft import Collector, Graph, MicrosoftAuth, TrustedHttp, workbook_items
from .scheduler import ProcessLock, Scheduler, SourceError, Store


class Service:
    def __init__(self, data, interval=300):
        self.data = data
        self.owner = ProcessLock(data)
        self.store = Store(data)
        self.http = TrustedHttp()
        self.auth = MicrosoftAuth(data, self.http)
        self.graph = Graph(self.auth, self.http)
        self.scheduler = Scheduler(self.store, Collector(self.graph), interval)
        self.thread = threading.Thread(target=self.scheduler.run, daemon=True)
        self.thread.start()
        self.candidates = {}
        self.candidate_lock = threading.Lock()
        self.benchmark_lock = threading.Lock()
        self.benchmark = {'status':'NOT_RUN'}

    def status(self):
        sources = self.store.sources()
        for s in sources:
            s.pop('config'); s.pop('cursor')
            s['freshness'] = 'UNVERIFIED' if s['last_success'] is None else 'OVERDUE' if time.time()-s['last_success'] > 600 else 'FRESH'
        return {'auth':self.auth.status(), 'sources':sources, 'events':self.store.events(),
                'scheduler_error':self.scheduler.fatal, 'interval_seconds':self.scheduler.interval,
                'http_requests':self.http.requests, 'blocked_destinations':self.http.blocked,
                'model_calls':0, 'benchmark':self.benchmark, 'mode':'MICROSOFT_GRAPH',
                'qualification':'Live source verification required; no model calls or browser automation in this service.'}

    def candidate(self, key, value):
        with self.candidate_lock:
            self.candidates[key] = value

    def selected(self, key):
        with self.candidate_lock:
            if key not in self.candidates:
                raise ValueError('Search or browse again before selecting this source.')
            return self.candidates[key]

    def action(self, route, body):
        if route == 'configure':
            self.auth.configure(body['client_id'], body['tenant_id']); return self.auth.status()
        if route == 'signin':
            return self.auth.start()
        if route == 'chats':
            matches = self.graph.chats(str(body.get('query',''))[:200])
            for c in matches: self.candidate('chat:'+c['id'],c)
            return {'matches':matches}
        if route == 'watch-chat':
            c = self.selected('chat:'+body['chat_id'])
            # Exact ID selected from current discovery, not a guessed name match.
            ident = self.store.add('teams', c['name'], {'chat_id':c['id']})
            return {'source_id':ident, 'message':'Monitoring QA chat: '+c['name'], 'chat_id':c['id']}
        if route == 'site':
            site = self.graph.site(body['url'])
            host = urlsplit(site['webUrl']).hostname
            self.candidate('site:'+site['id'],{'host':host,'name':site.get('displayName','SharePoint')})
            drives = self.graph.drives(site['id'])
            for d in drives:self.candidate('drive:'+d['id'], {'host':host,'name':d['name']})
            return {'site_id':site['id'],'name':site.get('displayName'),'drives':[{'id':d['id'],'name':d['name']} for d in drives]}
        if route == 'files':
            drive = self.selected('drive:'+body['drive_id'])
            folder = body.get('folder_id','root')
            if folder != 'root': self.selected('folder:'+body['drive_id']+':'+folder)
            items = self.graph.children(body['drive_id'],folder)
            result=[]
            for item in items:
                if 'folder' in item:
                    self.candidate('folder:'+body['drive_id']+':'+item['id'], item)
                    result.append({'id':item['id'],'name':item['name'],'folder':True})
                elif item.get('name','').lower().endswith('.xlsx'):
                    self.candidate('file:'+body['drive_id']+':'+item['id'], {**drive,'file_name':item['name']})
                    result.append({'id':item['id'],'name':item['name'],'folder':False})
            return {'items':result}
        if route == 'workbook':
            file = self.selected('file:'+body['drive_id']+':'+body['item_id'])
            sheets = self.graph.workbook(body['drive_id'],body['item_id'],file['host'])
            return {'sheets':[{'name':name,'rows':len(rows),'preview':rows[:10]} for name,rows in sheets.items()]}
        if route == 'watch-workbook':
            file = self.selected('file:'+body['drive_id']+':'+body['item_id'])
            config = {k:body[k] for k in ('drive_id','item_id','sheet','header_row','id_column','columns')}
            if not isinstance(config['columns'],list) or not all(isinstance(x,str) for x in config['columns']): raise ValueError('Select columns to monitor')
            config['host'] = file['host']
            sheets = self.graph.workbook(config['drive_id'], config['item_id'],config['host'])
            items = workbook_items(sheets,config)
            ident = self.store.add('sharepoint',file['file_name']+' / '+config['sheet'],config)
            return {'source_id':ident,'mapped_rows':len(items),'message':'Worksheet mapping validated. The scheduler will establish its baseline.'}
        if route == 'enabled':
            if type(body.get('enabled')) is not bool:raise ValueError('enabled must be boolean')
            self.store.enabled(body['id'],body['enabled']);return {'ok':True}
        if route == 'review':
            self.store.review(int(body['id']));return {'ok':True}
        if route == 'benchmark':
            if not self.benchmark_lock.acquire(blocking=False): raise ValueError('Scheduler test already running')
            self.benchmark={'status':'RUNNING'}
            def run():
                try:
                    result=subprocess.run([sys.executable,'-m','patcwatch.benchmark','--output',str(self.data/'scheduler-test.json')],
                                          capture_output=True,timeout=120)
                    if result.returncode: self.benchmark={'status':'FAILED','detail':'See local service logs or rerun CLI test.'}
                    else: self.benchmark={'status':'COMPLETE','report':json.loads((self.data/'scheduler-test.json').read_text())}
                except Exception:self.benchmark={'status':'FAILED'}
                finally:self.benchmark_lock.release()
            threading.Thread(target=run,daemon=True).start()
            return self.benchmark
        raise ValueError('Unknown action')

    def close(self):
        self.scheduler.stop.set()
        self.thread.join(timeout=35)
        # Never unlock storage while a collector may still be running.
        if not self.thread.is_alive():
            self.store.close();self.owner.close()
