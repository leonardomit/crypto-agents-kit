import json,time,datetime as dt
for c in ['BTC','ETH']:
    B={x['instrument_name']:x for x in json.load(open(f'deribit_book_{c}.json'))['result']}
    I=json.load(open(f'deribit_inst_{c}.json'))['result']
    now=time.time()*1000
    exps=sorted(set(i['expiration_timestamp'] for i in I))
    tgt=min(exps,key=lambda e:abs((e-now)/864e5-7))
    print(c,'expiries(days):',[round((e-now)/864e5,2) for e in exps[:8]],'chosen',round((tgt-now)/864e5,2),dt.datetime.utcfromtimestamp(tgt/1000))
    puts=[i for i in I if i['expiration_timestamp']==tgt and i['option_type']=='put']
    i0=puts[0];print(' contract_size',i0['contract_size'],'min_trade',i0['min_trade_amount'],'tick',i0['tick_size'],'settle',i0.get('settlement_currency'),i0.get('instrument_type'))
    S=B[puts[0]['instrument_name']]['underlying_price']
    print(' underlying',S)
    for pct in [0,0.05,0.10]:
        K=S*(1-pct)
        p=min(puts,key=lambda i:abs(i['strike']-K))
        b=B[p['instrument_name']]
        bid,ask,mark=b['bid_price'],b['ask_price'],b['mark_price']
        u=b['underlying_price']
        f=lambda x: None if x is None else round(x*u,2)
        print(f"  {pct:.0%} {p['instrument_name']} K={p['strike']} bid={bid} ask={ask} mark={mark} bidUSD={f(bid)} askUSD={f(ask)} markUSD={f(mark)} minsizeAskUSD={None if ask is None else round(ask*u*p['min_trade_amount'],2)} markIV={b['mark_iv']} bidIV={b.get('bid_iv')} askIV={b.get('ask_iv')} OI={b['open_interest']} vol24h={b['volume']}")
