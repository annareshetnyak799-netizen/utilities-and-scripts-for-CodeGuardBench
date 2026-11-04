"""Optional HTTPS adapter with process-safe conservative RUB reservations.
No credential or provider body is written to logs. Timeout reservations stay charged.
"""
import ast,contextlib,fcntl,json,os,random,re,time,urllib.request,urllib.error,uuid
from pathlib import Path
from judge.io import dump
class ProviderError(Exception):pass
@contextlib.contextmanager
def lock(path):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('a') as f:
  fcntl.flock(f,fcntl.LOCK_EX)
  try:yield
  finally:fcntl.flock(f,fcntl.LOCK_UN)
def credential(path):
 text=Path(path).read_text().strip()
 try:
  node=ast.parse(text).body[0];value=ast.literal_eval(node.value)
 except (SyntaxError,ValueError,AttributeError,IndexError):value=text.split('=',1)[-1].strip().strip('\"\'')
 if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,}',value):raise ProviderError('invalid_credential_file')
 return value
class Budget:
 def __init__(self,path,limit):self.path=Path(path);self.limit=limit
 def reserve(self,amount):
  with lock(str(self.path)+'.lock'):
   ledger=json.loads(self.path.read_text()) if self.path.exists() else {'limit_rub':self.limit,'entries':[]}
   if ledger['limit_rub']!=self.limit:raise ProviderError('budget_limit_changed')
   if sum(e['charged_rub'] for e in ledger['entries'])+amount>self.limit:raise ProviderError('budget_exhausted')
   ident=uuid.uuid4().hex;ledger['entries'].append({'id':ident,'reserved_rub':amount,'charged_rub':amount,'status':'reserved_unknown_actual'})
   dump(self.path,ledger);return ident
 def settle(self,ident,cost,metadata):
  with lock(str(self.path)+'.lock'):
   ledger=json.loads(self.path.read_text());entry=next(e for e in ledger['entries'] if e['id']==ident)
   entry.update(charged_rub=cost,status='usage_estimate',**metadata);dump(self.path,ledger)
class API:
 def __init__(self,c,budget):
  self.c=c;self.budget=budget
  if c.get('base_url')!='https://api.proxyapi.ru/v1' or c.get('allow_network') is not True:raise ProviderError('network_not_authorized')
 def complete(self,messages):
  c=self.c;content=json.dumps(messages,ensure_ascii=False);input_bound=len(content.encode())+512
  if input_bound>c.get('max_input_bytes',120000):raise ProviderError('input_too_long_no_truncation')
  maximum=c.get('max_tokens',1500);price=c['rub_per_million'];reserve=(input_bound*price['input']+maximum*price['output'])/1e6*1.10
  body={'model':c['model_id'],'messages':messages,'max_tokens':maximum,'response_format':{'type':'json_object'}}
  body.update(c.get('parameters',{}));key=credential(c['credential_file'])
  for attempt in range(c.get('retries',1)+1):
   token=self.budget.reserve(reserve);start=time.monotonic()
   try:
    req=urllib.request.Request(c['base_url']+'/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
    with urllib.request.urlopen(req,timeout=c.get('timeout',60)) as response:r=json.load(response)
    usage=r.get('usage',{});pin=usage.get('prompt_tokens');pout=usage.get('completion_tokens')
    meta={'model_requested':c['model_id'],'model_returned':r.get('model'),'latency_s':time.monotonic()-start,'usage':usage,'finish_reason':r['choices'][0].get('finish_reason'),'budget_entry':token}
    if isinstance(pin,int) and isinstance(pout,int):
     cost=(pin*price['input']+pout*price['output'])/1e6;meta['estimated_rub']=cost;self.budget.settle(token,cost,{'model':c['model_id'],'usage':usage})
    else:meta['estimated_rub']=reserve;meta['cost_unknown']=True
    # Never retain hidden reasoning or log it as an explanation.
    value=r['choices'][0]['message'].get('content')
    if not isinstance(value,str):raise ProviderError('missing_response_content')
    return value,meta
   except urllib.error.HTTPError as e:
    # Error billing is uncertain: reservation retained, no response body persisted.
    if e.code not in (429,500,502,503,504) or attempt==c.get('retries',1):raise ProviderError('provider_http_'+str(e.code)) from None
    time.sleep(min(2**attempt+random.random(),5))
   except (TimeoutError,urllib.error.URLError):raise ProviderError('provider_transport_timeout') from None
   except (ValueError,KeyError,IndexError):raise ProviderError('provider_response_invalid') from None
