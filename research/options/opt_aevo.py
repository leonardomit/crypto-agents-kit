import json,time,subprocess
now=time.time()
out={}
for a in ['BTC','ETH']:
    M=[m for m in json.load(open(f'aevo_mk_{a}.json')) if m['option_type']=='put' and m['is_active']]
    exps=sorted(set(int(m['expiry'])//10**9 for m in M))
    print(a,'expiries days',[round((e-now)/86400,2) for e in exps])
    tgt=min(exps,key=lambda e:abs((e-now)/86400-7))
    P=[m for m in M if int(m['expiry'])//10**9==tgt]
    S=float(P[0]['index_price']);print(' index',S,'chosen',round((tgt-now)/86400,2),'amount_step',P[0]['amount_step'],'min_order_value',P[0]['min_order_value'])
    for pct in [0,0.05,0.10]:
        p=min(P,key=lambda m:abs(float(m['strike'])-S*(1-pct)))
        ob=json.loads(subprocess.check_output(['curl','-s',f"https://api.aevo.xyz/orderbook?instrument_name={p['instrument_name']}"]))
        ins=json.loads(subprocess.check_output(['curl','-s',f"https://api.aevo.xyz/instrument/{p['instrument_name']}"]))
        bb=ob.get('bids',[[None]])[:1]; aa=ob.get('asks',[[None]])[:1]
        print(f"  {pct:.0%} {p['instrument_name']} OTM={(1-float(p['strike'])/S):.2%} mark={p['mark_price']} iv={p['greeks']['iv']} bid={bb} ask={aa} OI={ins.get('open_interest') if isinstance(ins,dict) else ins} markets={ {k:ins.get(k) for k in ['best_bid','best_ask','mark_price','index_price']} if isinstance(ins,dict) else ''}")
