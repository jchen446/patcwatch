"""Isolated real-HTTP scheduler test. Synthetic Microsoft service, virtual clock."""
import argparse
import hashlib
import io
import json
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlencode
from urllib.request import urlopen

from .microsoft import Collector, Graph, TrustedHttp
from .scheduler import Scheduler, SourceError, Store
from .server import save_json


def run(output):
    from openpyxl import Workbook
    started = time.perf_counter()
    state = {'cycle':0, 'messages':[{'id':str(i),'body':{'content':'Feedback '+str(i)},'attachments':[]} for i in range(500)],
             'rows':[[str(i),'Row '+str(i)] for i in range(500)],'xlsx':b'', 'requests':0}
    def workbook():
        book=Workbook();sheet=book.active;sheet.title='QA';sheet.append(['ID','Feedback'])
        for row in state['rows']:sheet.append(row)
        if state['cycle']==60:sheet.append(state['rows'][0])
        stream=io.BytesIO();book.save(stream);book.close();state['xlsx']=stream.getvalue()
    workbook()
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            state['requests']+=1
            p=urlsplit(self.path);cycle=state['cycle'];status=200;headers={}
            if '/messages' in p.path:
                if cycle==20:status=429;headers={'Retry-After':'900'};value={}
                elif cycle==50:status=401;value={}
                else:
                    offset=int(parse_qs(p.query).get('offset',['0'])[0]);value={'value':state['messages'][offset:offset+50]}
                    if offset+50<len(state['messages']):value['@odata.nextLink']='https://graph.microsoft.com/v1.0/chats/qa/messages?'+urlencode({'offset':offset+50})
                    if cycle==40:value['@odata.nextLink']='https://untrusted.example/steal'
                raw=json.dumps(value).encode()
            elif p.path=='/download':
                raw=b'corrupt archive' if cycle==70 else state['xlsx']
            elif p.path=='/v1.0/drives/drive/items/book':
                if cycle==30:status=503;raw=b'{}'
                else:raw=json.dumps({'name':'QA.xlsx','size':len(state['xlsx']),'eTag':'stable-'+str(cycle),
                    'webUrl':'https://example.sharepoint.com/sites/QA/QA.xlsx',
                    '@microsoft.graph.downloadUrl':'https://example.sharepoint.com/download'}).encode()
            else:status=404;raw=b'{}'
            self.send_response(status)
            for k,v in headers.items():self.send_header(k,v)
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    http=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    counts={'blocked':0,'allowed_connections':0}
    def guard(event,args):
        if event=='socket.connect':
            address=args[1]
            if not isinstance(address,tuple) or address[:2]!=('127.0.0.1',http.server_port):
                counts['blocked']+=1;raise PermissionError('External connection blocked by benchmark')
            counts['allowed_connections']+=1
        if event=='socket.getaddrinfo' and args[0]!='127.0.0.1':
            counts['blocked']+=1;raise PermissionError('External DNS blocked by benchmark')
        if event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn'):
            counts['blocked']+=1;raise PermissionError('Process launch blocked by benchmark')
    sys.addaudithook(guard)
    class Token:
        refreshes=0
        def token(self,force=False):
            if force:self.refreshes+=1
            return 'SYNTHETIC-NOT-A-CREDENTIAL'
    class Response:
        def __init__(self,status,headers,content):self.status_code,self.headers,self.content=status,headers,content
        def json(self):return json.loads(self.content)
    class Http:
        def request(self,method,url,download_host=None,**kwargs):
            p=urlsplit(url)
            if method!='GET' or p.scheme!='https' or p.hostname not in {'graph.microsoft.com','example.sharepoint.com'}:raise SourceError('NETWORK_DESTINATION_DENIED')
            from urllib.error import HTTPError
            try:
                with urlopen('http://127.0.0.1:'+str(http.server_port)+p.path+('?' +p.query if p.query else ''),timeout=10) as r:return Response(r.status,dict(r.headers),r.read())
            except HTTPError as e:return Response(e.code,dict(e.headers),e.read())
        def get(self,url,**kwargs):return self.request('GET',url,**kwargs)
    token=Token();graph=Graph(token,Http());now=[1789048800.0];faults=set();expected_events=0;source_checks=0;unchanged_extra_ticks=0
    oracle={};last_success={};assertions=0
    try:
        with tempfile.TemporaryDirectory(prefix='patcwatch-scheduler-') as tmp:
            root=Path(tmp);store=Store(root)
            teams=store.add('teams','Synthetic QA chat',{'chat_id':'qa'})
            excel=store.add('sharepoint','Synthetic QA worksheet',{'drive_id':'drive','item_id':'book','host':'example.sharepoint.com','sheet':'QA','header_row':1,'id_column':'ID','columns':['Feedback']})
            scheduler=Scheduler(store,Collector(graph,lambda:now[0]),300,lambda:now[0])
            for cycle in range(100):
                state['cycle']=cycle
                if cycle and cycle%10==0:
                    state['messages'][0]['body']['content']='Edited feedback '+str(cycle)
                    state['rows'][0][1]='Edited row '+str(cycle)
                if cycle==15:
                    state['messages'].append({'id':'new','body':{'content':'New report'},'attachments':[]})
                    state['rows'].append(['new','New worksheet report'])
                workbook()
                before_cursor={s['id']:s['cursor'] for s in store.sources()}
                source_checks+=scheduler.tick()
                for s in store.sources():
                    if s['status']!='CHECKED':
                        faults.add(s['status']);assert s['last_success']==last_success.get(s['id']);assert s['cursor']==before_cursor[s['id']];assertions+=2
                    if s['last_success']!=now[0]:continue
                    if s['id']==teams:
                        current={r['id']:json.dumps({'text':r['body']['content'],'deleted':False,'attachments':[]},sort_keys=True) for r in state['messages']}
                    else:current={r[0]:json.dumps({'Feedback':r[1]},sort_keys=True) for r in state['rows']}
                    if s['id'] in oracle:expected_events+=sum(oracle[s['id']].get(k)!=v for k,v in current.items())
                    oracle[s['id']]=current;last_success[s['id']]=s['last_success']
                unchanged_extra_ticks+=1
                assert scheduler.tick()==0;assertions+=1
                if cycle in (24,49,74):
                    store.close();store=Store(root);scheduler=Scheduler(store,Collector(graph,lambda:now[0]),300,lambda:now[0])
                    assert scheduler.tick()==0;assertions+=1
                now[0]+=300
            actual=store.db.execute('SELECT count(*) FROM event').fetchone()[0]
            assert actual==expected_events and actual>0;assertions+=1
            assert {'THROTTLED','SERVICE_UNAVAILABLE','SIGN_IN_REQUIRED','PAGINATION_DESTINATION_DENIED','DUPLICATE_OR_MISSING_ROW_ID','INVALID_WORKBOOK'} <= faults;assertions+=1
            store.close()
        # Test production transport policy independently of the fixture rewriting transport.
        production=TrustedHttp()
        try:production.get('https://api.openai.com/v1/models')
        except SourceError as e:assert e.status=='NETWORK_DESTINATION_DENIED';assertions+=1
        else:raise AssertionError('Unexpected external destination accepted')
        with socket.socket() as probe:
            try:probe.connect(('192.0.2.1',443))
            except PermissionError:assertions+=1
            else:raise AssertionError('External network probe was not blocked')
        result={'passed':True,'mode':'SYNTHETIC_MICROSOFT_HTTP_FIXTURE','cycles':100,'source_checks':source_checks,
            'initial_items':1000,'restart_recoveries':3,'duplicate_ticks_suppressed':unchanged_extra_ticks,
            'expected_events':expected_events,'actual_events':actual,'assertions':assertions,
            'faults_verified':sorted(faults),'fixture_http_requests':state['requests'],'model_calls':0,
            'external_connections':0,'blocked_external_probes':counts['blocked'],
            'production_transport_denials':production.blocked,'synthetic_refresh_attempts':token.refreshes,
            'elapsed_seconds':round(time.perf_counter()-started,3),
            'limits':'Virtual schedule, real loopback HTTP, real scheduler/SQLite/Graph readers/XLSX parser. Microsoft login and real refresh-token renewal are not verified. No live source state used. Build/supervisor model usage excluded.'}
        save_json(output,result);return result
    finally:
        http.shutdown();http.server_close();thread.join(timeout=5)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(run(args.output),indent=2))
