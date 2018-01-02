import poloniex

API_KEY = '7IB7HF78-OPA5G774-3H1X9DV2-K5A60A7Y'
SECRET_KEY = '3a6fb9e37289e90ba23da5e89cf27eed9dd2e090f3f244ba8200cf70b6818df9e24c21671e60885412ca41e36596299aaebb50146d693462020ac1e99fb74bbd'

poloniex_api = poloniex.Poloniex(API_KEY, SECRET_KEY)

print(poloniex_api.returnOpenOrders()['BTC_VTC'])
