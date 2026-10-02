import json,time,subprocess
now=time.time()
def post(ep,d): return json.loads(subprocess.check_output(['curl','-s','-X','POST',f'https://api.lyra.finance/public/{ep}','-H','Content-Type: application/json','-d',json.dumps(d)]))
for c in ['BTC','ETH']:
    I=[i for i in json.load(open(f'derive_inst_{c}.json'))['result'] if i['option_details']['option_type']=='P' and i['is_active']]
    exps=sorted(set(i['option_details']['expiry'] for i in I))
    print(c,'expiries days',[round((e-now)/86400,2) for e in exps])
    tgt=min(exps,key=lambda e:abs((e-now)/86400-7))
    P=[i for i in I if i['option_details']['expiry']==tgt]
    t=post('get_ticker',{'instrument_name':P[0]['instrument_name']})['result']
    S=float(t['index_price']); print(' index',S,'chosen',round((tgt-now)/86400,2),'min_amount',P[0]['minimum_amount'],'step',P[0]['amount_step'],'base_fee',P[0]['base_fee'],'taker',P[0]['taker_fee_rate'])
    for pct in [0,0.05,0.10]:
        p=min(P,key=lambda i:abs(float(i['option_details']['strike'])-S*(1-pct)))
        t=post('get_ticker',{'instrument_name':p['instrument_name']})['result']
        op=t.get('option_pricing') or {}
        st=t.get('stats') or {}
        print(f"  {pct:.0%} {p['instrument_name']} OTM={(1-float(p['option_details']['strike'])/S):.2%} bid={t['best_bid_price']}x{t['best_bid_amount']} ask={t['best_ask_price']}x{t['best_ask_amount']} mark={t['mark_price']} iv={op.get('iv')} bid_iv={op.get('bid_iv')} ask_iv={op.get('ask_iv')} OI={st.get('open_interest')} vol24h_contracts={st.get('contract_volume')} usd_vol={st.get('usd_volume')}")
