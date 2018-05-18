# poloniex-trade

Poloniex ready to use trade bot.

## Global variables

**API_KEY** - Your api key.

**SECRET_KEY** - Your secret key.

**MARKETS** - Array of markets you want to monitor (e.g. BTC_ETH).

**CAN_SPEND** - How much the bot must spend for buy orders (in base currency).

**MARK_UP** - How much you want to earn from each deal (in base currency, exclude comission).

**STOCK_FEE** - Exchange comission (in percents).

**ORDER_LIFE_TIME** - After which time an order considered as suspended (in minutes).

**USE_MACD** - Use MACD function to determine trends.

**BEAR_PERC** - How much rate should be changes to consider current market as bear (in percents).

**BULL_PERC** - How much rate should be changes to consider current market as bull (in percents).

**USE_LOG** - Do you want the bot to log every its action? (to terminal and txt file)?