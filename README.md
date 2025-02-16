# trading_bot
This is a python trading bot including : 
- frontend web interface to configure and monitor bot activity (using flask)
- backend with two main functionnality
    - backtest : retrieve historical data and backtest your strategy for a specific amount of time
    - run : run the bot in a dedicated thread, monitoring real-time data and making trades according to defined strategy
  
This bot is using ccxt library to interact (fetching data and making trades) with most common trading platofroms through their respective API 

First version only integrates bitget platform and a "martingale" strategy on perpetual futures contracts 

Other strategies can be implemented by adding a strategy_name.py file inside app folder : 
- the python file must contain a class implementing the strategy, see Martingale.py file to get the correct structure
- naming is important, for a strategy named "cleverstrat", the python file must be named "Cleverstrat.py" and strategy class inside the file "CleverstratStrategy"
- if you need to use other indicators than RSI or PivotHL (already implemented, see Martingale.py and models.py (Candles class)) :
  - you need to add the corresponding method to models.py Candles class
  - and modify calc_indicators method to include the new indicator
- indicators value are stored in cache csv file to prevent recalculation : calc_indicators method only calculates indicator for candles in history not having a value
