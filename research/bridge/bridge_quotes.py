"""Compara cotações de bridge USDC (Across, LI.FI, Relay, deBridge) p/ US$20. Read-only, HTTP público.

Env: BRIDGE_SOL_USER = qualquer pubkey Solana válida usada só para cotação (Relay exige).
Saída: quotes.json no diretório atual.
"""
import json,os,subprocess,time,urllib.parse as up
def get(url,data=None):
    cmd=['curl','-s','-m','30',url]
    if data is not None: cmd=['curl','-s','-m','30','-X','POST',url,'-H','Content-Type: application/json','-d',json.dumps(data)]
    try: return json.loads(subprocess.check_output(cmd))
    except Exception as e: return {'_err':str(e)}
USDC={42161:('0xaf88d065e77c8cC2239327C5EDb3A432268e5831',6),8453:('0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',6),1:('0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',6),56:('0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d',18),'sol':('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',6)}
DEAD='0x000000000000000000000000000000000000dEaD'
SOLADDR='11111111111111111111111111111111'
routes=[(42161,8453),(42161,1),(42161,56),('sol',8453),('sol',42161)]
out={}
print('fetched',time.strftime('%F %T %Z'))
for s,d in routes:
    key=f'{s}->{d}';r={}
    amt=20*10**USDC[s][1]
    # Across (EVM only)
    if s!='sol':
        a=get(f"https://app.across.to/api/suggested-fees?inputToken={USDC[s][0]}&outputToken={USDC[d][0]}&originChainId={s}&destinationChainId={d}&amount={amt}")
        r['across']=a
    # LI.FI
    lf={'sol':'SOL',42161:'ARB',8453:'BAS',1:'ETH',56:'BSC'}
    fa=SOLADDR if s=='sol' else DEAD
    ta=DEAD
    l=get("https://li.quest/v1/quote?"+up.urlencode(dict(fromChain=lf[s],toChain=lf[d],fromToken=USDC[s][0],toToken=USDC[d][0],fromAmount=amt,fromAddress=fa,toAddress=ta)))
    r['lifi']=l
    # Relay
    rc={'sol':792703809,42161:42161,8453:8453,1:1,56:56}
    rl=get("https://api.relay.link/quote",dict(user=fa if s!='sol' else os.environ.get('BRIDGE_SOL_USER', SOLADDR),recipient=DEAD,originChainId=rc[s],destinationChainId=rc[d],originCurrency=USDC[s][0],destinationCurrency=USDC[d][0],amount=str(amt),tradeType='EXACT_INPUT'))
    r['relay']=rl
    # deBridge
    dc={'sol':7565164,42161:42161,8453:8453,1:1,56:56}
    db=get("https://dln.debridge.finance/v1.0/dln/order/quote?"+up.urlencode(dict(srcChainId=dc[s],srcChainTokenIn=USDC[s][0],srcChainTokenInAmount=amt,dstChainId=dc[d],dstChainTokenOut=USDC[d][0],prependOperatingExpenses='true')))
    r['debridge']=db
    out[key]=r
json.dump(out,open('quotes.json','w'),indent=1)
