import time
from datetime import datetime
from typing import List, Dict, Literal
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import app
from app import login
from app.api import Api
from app.files_rw import correct_types_from_strings, CsvRW, read_config_file
from app.logging import strategy_logger


class User(UserMixin):
    def __init__(self):
        self.password_hash = app.config['PWD_KEY']
        self.username = "NoarDsir"
        self.id = 1

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login.user_loader
def load_user(_id):
    return User()


class Candles:
    def __init__(self, api:Api, symbol, timeframe,max_history_store:int=100):
        self.csv_file_path = "app/datas/"+symbol.replace("/", "").replace(":","_") + "_" + timeframe  #history_file
        self.api = api
        self.symbol = symbol
        self.timeframe = timeframe
        self.timeframe_in_seconds=self.timeframe_to_seconds(self.timeframe)
        self.history = [] #self.get_candles_history(min_bars_back,indicators,True)
        self.calculators={}
        self.backtest_data_reader=None
        self.backtest_candles=None
        self.max_history_store=max_history_store

    ###### BACKTEST METHODS ######

    # Prepare backtest :
    # Check history for missing candles (before, in file and after)
    # Calculate indicators
    # Save complete file to use in backtest
    def prepare_backtest(self,backtest_start_time:int,indicators=None,min_bars_back=0):
        ## check first and last candle saved
        reader = CsvRW(self.csv_file_path)
        oldest_time = time.time()
        if reader.csv_file_path is not None:
            reader.read_normal()
            first_line=reader.get_next_line()
            if first_line is not None:
                oldest_time = int(float(first_line['Time']))

        ## Open tempfile to write to and old file to read
        csv_rw=CsvRW(self.csv_file_path)
        csv_rw.read_write_to_csv()
        # Write header
        csv_rw.write_line(['Time','Open','High','Low','Close','Volume']+list(indicators.keys()))
        # Write the lines missing before
        since = backtest_start_time - self.timeframe_in_seconds*min_bars_back - 1 #Start time - min bars to have relevant indicators - 1 to include first bar
        new_lines=self.get_history_api(since,oldest_time-1)
        for api_line in new_lines:
            if int(float(api_line['Time'])) >= oldest_time: break  # Stop adding lines after first existing log (or current time) is reached
            api_line = self.calc_indicators(api_line, indicators)
            csv_rw.write_line(list(api_line.values()))
            since = int(float(api_line['Time']))
        del new_lines

        # Write the existing lines
        for csv_line in csv_rw.readline:
            time_line = int(float(csv_line['Time']))
            if since == csv_line['Time']:
                continue  # if doubble line, skip
            elif since + self.timeframe_in_seconds < time_line:  # if missing datas, fetch them
                new_lines=self.get_history_api(since+1,time_line-1)
                for api_line in new_lines:
                    if int(float(api_line['Time'])) >= time_line: break  # Stop adding lines after first existing log (or current time) is reached
                    api_line = self.calc_indicators(api_line, indicators)
                    csv_rw.write_line(list(api_line.values()))
                    since = int(float(api_line['Time']))
                del new_lines
            # Finally, write the csv line
            csv_line = self.calc_indicators(csv_line, indicators)
            csv_rw.write_line(list(csv_line.values()))
            since = int(float(csv_line['Time']))
        # Write the last lines from API
        new_lines = self.get_history_api(since+1,closed=True)
        for api_line in new_lines:
            api_line = self.calc_indicators(api_line, indicators)
            csv_rw.write_line(list(api_line.values()))
        del new_lines
        # Replace file by temp file and close all
        csv_rw.save_and_replace()
        del csv_rw

    ## Initiate backtest :
    # Create reader for the file (read from beginning)
    # Create generator to iterate inside file
    def get_backtest_candle(self):
        if self.backtest_data_reader is None:
            self.backtest_data_reader=CsvRW(self.csv_file_path)
            self.backtest_data_reader.read_normal()
        self.backtest_candles=self.candle_iterate()

    # Iterator to get each candle from file
    def candle_iterate(self):
        for candle in self.backtest_data_reader.readline:
            self.history[:0] = [candle]
            if len(self.history) > self.max_history_store: del self.history[-1]
            yield candle
        del self.backtest_data_reader
        return

    ###### REALTIME METHODS ######

    def get_candles_history(self, min_bars_back,indicators=None,closed=True):
        history = self.get_history_api(None, bars=min_bars_back,closed=closed) # Get necessary candles
        if indicators is not None:
            for index,candle in enumerate(history):
                history[index]=self.calc_indicators(candle,indicators) #Calc indicators
        append=CsvRW(self.csv_file_path)
        append.safe_append_to_csv(history)
        del append
        history.reverse() #Sort by time descending
        self.history = history
        return history

    def update_history(self,indicators=None,closed=True):
        new_lines = self.get_history_api(int(self.history[0].get('Time')) + 1,closed=closed)
        lines_added=len(new_lines)
        if indicators is not None:
            for index,candle in enumerate(new_lines):
                new_lines[index]=self.calc_indicators(candle,indicators)
        append=CsvRW(self.csv_file_path)
        append.safe_append_to_csv(new_lines)
        del append
        new_lines.reverse()
        self.history[:0] = new_lines
        if len(self.history)>self.max_history_store:del self.history[-1] # Avoid inifinite growing object
        return lines_added

    def get_history_api(self, since:int=None, until=None, bars=None, closed=True):
        #Round times to candle starts
        #if until is not None:until = until - until % self.timeframe_in_seconds
        #if since is not None:since = since - since % self.timeframe_in_seconds
        if until is None: #if until is not set, set it
            until = time.time()
            if closed:
                until = until - until % self.timeframe_in_seconds -1 # Round to last candle, -1 to avoid fetching current candle
        if since is None and bars is None:
            strategy_logger.exception('Missing one argument : since or bars required')
            return
        since = since if since is not None else int(until - bars * self.timeframe_in_seconds)
        since -=1 # Retrieve also the "since" candle
        candles_to_fetch = bars if bars is not None else int((until - since) / self.timeframe_in_seconds) #Number of candles to fetch
        lines_fetched = list()  #Initiate variable for API response
        if candles_to_fetch == 0:
            return lines_fetched
        while since + self.timeframe_in_seconds <= until:
            new_lines = self.api.get_ohlc(self.symbol, self.timeframe, since=since,until=until,limit=(candles_to_fetch if candles_to_fetch < 1000 else 1000))
            lines_fetched[:0] = new_lines
            candles_to_fetch -= len(new_lines)
            if len(new_lines) == 0 or candles_to_fetch == 0: break
            until = int(lines_fetched[0].get('Time')) -1
        return lines_fetched

    ###### INDICATORS METHODS ######

    def calc_indicators(self, candle,indicators: Dict):
        if 'RSI' in indicators:
            if not 'RSI' in self.calculators:self.calculators['RSI']=self.RSICalculator(14)
            candle['RSI']=self.calculators['RSI'].calc_rsi(**candle)
        if 'PivotsHL' in indicators:
            if not 'PivotsHL' in self.calculators:self.calculators['PivotsHL']=self.PivotCalculator(10)
            candle['PivotsHL']=self.calculators['PivotsHL'].calc_pivots(candle)
        return candle

    class RSICalculator:
        def __init__(self, length=14):
            self.gains = []
            self.losses = []
            self.length = length
            self.enough_candles = False
            self.avg_gain = None
            self.avg_loss = None

        def calc_rsi(self, Open, Close, **kwargs):
            """Indicator: Relative Strength Index (RSI)"""
            diff = float(Close) - float(Open)
            if not self.enough_candles:  # If less than "length" candles...save data
                self.gains.append(diff if diff > 0 else 0)
                self.losses.append(abs(diff) if diff < 0 else 0)
                if len(self.gains) == self.length:  # If enough candles, calc first average using SMA
                    self.enough_candles = True
                    self.avg_gain = sum(self.gains) / self.length
                    self.avg_loss = sum(self.losses) / self.length
                rsi = None
            else:  # Then we can calculate RSI value with RMA
                self.avg_gain = ((diff if diff > 0 else 0) + (self.length - 1) * self.avg_gain) / self.length
                self.avg_loss = ((abs(diff) if diff < 0 else 0) + (self.length - 1) * self.avg_loss) / self.length
                rsi = 100 * self.avg_gain / (self.avg_gain + self.avg_loss)
            return round(rsi,2) if rsi is not None else None

        def gen_candles_rsi(self, candles):
            for index, candle in enumerate(candles):
                candles[index]['RSI'] = self.calc_rsi(**candle)
            return candles

    class PivotCalculator:
        def __init__(self, width=10):
            self.highs = []
            self.lows = []
            self.width = width
            self.pivots={'high': None, 'low': None}

        def calc_pivots(self, candle):
            self.highs.append(float(candle['High']))
            self.lows.append(float(candle['Low']))
            if len(self.highs) > (2 * self.width + 1):
                self.highs.pop(0)
                self.lows.pop(0)
                if self.highs[10] == max(self.highs):
                    self.pivots['high'] = self.highs[10]
                elif self.lows[10] == min(self.lows):
                    self.pivots['low'] = self.lows[10]
                if self.pivots['low'] is not None and self.pivots['low'] > float(candle['Low']):
                    self.pivots['low'] = None
                if self.pivots['high'] is not None and self.pivots['high'] < float(candle['High']):
                    self.pivots['high'] = None
            return self.pivots.copy()

    @staticmethod
    def timeframe_to_seconds(timeframe):
        seconds = 0
        match timeframe:
            case '1d':
                seconds = 24 * 3600
            case '1h':
                seconds = 3600
            case '1m':
                seconds = 60
        return seconds


'''
    class Candle:
        def __init__(self, open=None, high=None, low=None, close=None, usdtVol=None, ts=None):
            self.open = open
            self.high = high
            self.low = low
            self.close = close
            self.usdtVol = usdtVol
            self.time = ts
            self.rsi=None
'''


class Strategy:
    def __init__(self, parameter_file=None, capital: float = 0, leverage: int = 1,
                 taker_fee: float = 0.0006, start_date=0,api:Api=None,symbol=None):
        if parameter_file is not None:
            parameters = read_config_file(parameter_file)['PARAMETERS']
            self.start_date = datetime.timestamp(
                datetime.strptime(parameters[0].pop('start_date'), '%Y-%m-%d %H:%M:%S'))
            parameters = correct_types_from_strings(parameters)[0]
            #self.capital = parameters['capital']
            self.leverage = parameters['leverage']
            self.symbol = parameters['symbol']
        else:
            self.capital = capital
            self.leverage = leverage
            self.start_date = start_date
            self.symbol=symbol
        self.position = Strategy.Trade()
        self.open_trades: List[Strategy.Trade] = []
        self.closed_trades: List[Strategy.Trade] = []
        self.open_orders: List[Strategy.Order] = []
        self.set_position()
        self.maintenance_margin = 0.005
        self.taker_fee = taker_fee
        self.last_known_price=None
        self.max_runup=0
        self.max_drawdown=0
        self.max_equity=capital
        self.min_equity=capital
        self.api=api
        self.min_qty=0.001
        self.liquidation_price=None
        if self.api is not None:
            try:
                self.api.set_position_mode(self.symbol,False)
                self.api.set_margin_mode(self.symbol, False)
            except BaseException as exception:
                strategy_logger.exception(exception)
            self.api.set_leverage(self.symbol,self.leverage)
            self.taker_fee=self.api.exchange.markets[self.symbol]['taker']
            self.maker_fee = self.api.exchange.markets[self.symbol]['maker']
            self.min_qty=self.taker_fee=self.api.exchange.markets[self.symbol]['limits']['amount']['min']
            self.maintenance_margin=self.api.fetch_margin_rate(self.symbol)


    def set_position(self):
        qty = 0
        amount = 0
        position = None
        for trade in self.open_trades:
            amount += trade.qty * trade.open_price
            qty += trade.qty

        if qty > 0:
            position = Strategy.Trade(self, self.open_trades[0].open_time, amount / qty, self.open_trades[0].long, qty)
        self.position = position

    def open_order(self, order:'Strategy.Order',backtest=False):
        print(order)
        order.size = self.min_qty * (int(order.size/self.min_qty)) #truncate to min-qty
        error=False
        if not backtest:
            try:
                response=self.api.send_order(self.symbol, 'buy' if order.long else 'sell', order.size, order.type,order.price,order.stop)
                order.size=response['size']
                order.price=response['price']
                order.long=response['long']
                order.id=response['id']
            except BaseException as exception:
                strategy_logger.exception(exception)
                error=True
        if not error:
            if order.type=='market' and not order.stop:
                self.open_trades.append(Strategy.Trade(self, order.time, order.price, order.long, order.size, open_name=order.name, margin=order.margin))
                self.set_position()
            else:
                self.open_orders.append(order)
            return order


    def edit_order(self,order:'Strategy.Order',backtest=False):
        error=False
        order.size = self.min_qty * (int(order.size/self.min_qty)) #truncate to min-qty
        if not backtest:
            try:
                response=self.api.edit_order(order.id,self.symbol,'buy' if order.long else 'sell',order.size,order.price,order.type,order.stop)
                order.id=response['id']
                order.price=response['price']
                order.long=response['long']
                order.size=response['size']
            except BaseException as exception:
                error=True
                strategy_logger.exception(exception)
        if not error:
            for index in range(len(self.open_orders)):
                if self.open_orders[index].id == order.id:
                    self.open_orders[index].price= order.price
                    self.open_orders[index].long = order.long
                    self.open_orders[index].size = order.size
                    self.open_orders[index].stop = order.stop

    def cancel_orders(self,_id=None,backtest=False):
        if _id is None:
            if not backtest:
                self.api.cancel_all_order(self.symbol)
            self.open_orders=[]
        else:
            if not backtest:
                self.api.cancel_order(_id,self.symbol)
            for order in self.open_orders.copy():
                if order.id == _id:
                    self.open_orders.remove(order)

    def close_order(self, order:'Strategy.Order',backtest=False):
        error = False
        order.size = self.min_qty * (int(order.size/self.min_qty)) #truncate to min_qty
        if self.position is not None and order.size > 0 :
            if not backtest:
                try:
                    response = self.api.send_order(self.symbol, 'sell' if self.position.long else 'buy', order.size, 'market')
                    order.size=response['size']
                    order.price=response['price']
                except BaseException as exception:
                    error=True
                    strategy_logger.exception(exception)
            if not error:
                size_left = order.size
                while size_left > 0 and len(self.open_trades) > 0:
                    trade = self.open_trades.pop(0)
                    size_left = trade.close_trade(order.time, order.price, order.size)
                    if size_left < 0:
                        self.open_trades.insert(0, Strategy.Trade(self, trade.open_time, trade.open_price, trade.long,
                                                                  abs(size_left), open_name=trade.open_name))
                    trade.close_name = order.name
                    self.closed_trades.append(trade)
                self.set_position()


    def check_orders(self, candle):
        orders_filled = []

        for index, order in enumerate(self.open_orders):
            if order.check_order(candle) is not None:
                orders_filled.append(self.open_orders.pop(index))

        return orders_filled

    def get_realised_profit(self):
        profit=0
        for t in self.closed_trades: profit+=t.get_profit()
        return profit

    def get_realised_pnl(self):
        return self.get_realised_profit()/self.capital

    def get_open_profit(self,price=None):
        profit=0
        if price is not None:
            profit = 0
            for t in self.open_trades: profit += t.get_profit(price)
        elif self.last_known_price is not None:
            profit = 0
            for t in self.open_trades: profit += t.get_profit(self.last_known_price)
        return profit

    def get_open_pnl(self):
        return self.get_open_profit()/self.capital

    def get_profit(self):
        return self.get_open_profit()+self.get_realised_profit()

    def get_pnl(self):
        return self.get_profit()/self.capital

    def set_runup_drawdown(self,candle):
        if self.get_equity()>self.max_equity:
            self.max_equity=self.get_equity()
        elif self.get_equity()<self.min_equity:
            self.min_equity=self.get_equity()
        if self.last_known_price is not None:
            for trade in self.open_trades:
                trade.set_runup_drawdown(candle)
        if self.position is None:
            runup=None
            drawdown = None
        elif self.position.long:
            runup=candle['High']
            drawdown=candle['Low']
        else:
            runup = candle['Low']
            drawdown = candle['High']
        if (self.max_runup is None and self.get_open_equity(runup) - self.min_equity>0) or (self.max_runup is not None and self.get_open_equity(runup) -self.min_equity >self.max_runup):
            self.max_runup   = self.get_open_equity(runup) - self.min_equity
        if (self.max_drawdown is None and self.get_open_equity(drawdown) - self.max_equity<0) or (self.max_drawdown is not None and self.get_open_equity(drawdown) - self.max_equity<self.max_drawdown):
            self.max_drawdown = self.get_open_equity(drawdown) - self.max_equity

    def get_runup(self):
        return 100*self.max_runup/self.max_equity
    def get_drawdown(self):
        return 100*self.max_drawdown/self.max_equity

    def get_equity(self):
        return self.capital + self.get_realised_profit()
    def get_open_equity(self, price=None):
        return self.capital + self.get_realised_profit() + self.get_open_profit(price)

    class Trade:
        def __init__(self, strategy=None, open_time=None, open_price=None, long=True, qty=None, close_time=None,
                     close_price=None, open_name=None, close_name=None,margin=None):
            self.strategy = strategy
            self.open_time = open_time
            self.open_price = open_price
            self.long = long
            self.qty = qty
            self.close_time = close_time
            self.close_price = close_price
            self.drawdown_price = None
            self.runup_price = None
            self.margin = margin if margin is not None else self.set_margin()
            self.open_name = open_name
            self.close_name = close_name
            self.id=None

        def __str__(self):
            return f"{datetime.fromtimestamp(self.open_time)} {self.open_name} {'buy' if self.long else 'sell'} {self.qty} @{self.open_price} close {self.close_name} @{self.close_price}"

        def set_runup_drawdown(self, candle):
            if self.long:
                if (self.runup_price is not None and candle['High'] > self.runup_price) or (self.runup_price is None and candle['High']>self.open_price): self.runup_price = candle['High']
                if (self.drawdown_price is not None and candle['Low'] < self.drawdown_price) or (self.drawdown_price is None and candle['Low']<self.open_price): self.drawdown_price = candle['Low']
            else:
                if (self.runup_price is not None and candle['Low'] < self.runup_price) or (self.runup_price is None and candle['Low']<self.open_price): self.runup_price = candle['Low']
                if (self.drawdown_price is not None and candle['High'] > self.drawdown_price) or (self.drawdown_price is None and candle['High']>self.open_price): self.drawdown_price = candle['High']

        def get_drawdown(self):
            if self.drawdown_price is None:
                return None
            elif self.long:
                return self.drawdown_price / self.open_price -1
            else:
                return 1- self.drawdown_price / self.open_price

        def get_runup(self):
            if self.runup_price is None:
                return None
            elif self.long:
                return self.runup_price / self.open_price - 1
            else:
                return 1 - self.runup_price / self.open_price

        def get_pnl(self, price=None):
            if price is None and self.close_price is not None:
                if self.long:
                    return self.close_price / self.open_price - 1
                else:
                    return 1 - self.close_price / self.open_price
            elif price is not None and self.open_price is not None:
                if self.long:
                    return price / self.open_price - 1
                else:
                    return 1 - price / self.open_price
            return None

        def get_profit(self,price=None):
            if price is None and self.close_price is not None:
                if self.long:
                    return self.close_price*self.qty - self.open_price*self.qty
                else:
                    return self.open_price*self.qty - self.close_price*self.qty
            elif price is not None and self.open_price is not None:
                if self.long:
                    return price*self.qty - self.open_price*self.qty
                else:
                    return self.open_price*self.qty - price*self.qty
            return None


        def close_trade(self, _time, price, qty):
            self.close_price = price
            self.close_time = _time
            # If trade bigger, reduce to order qty and return qty left in trade
            close_qty_left = qty - self.qty
            if close_qty_left < 0:
                self.qty = qty
            # Return qty left to close (positive) or qty left in trade (negative)
            return close_qty_left

        def set_margin(self):
            self.margin = None
            if self.qty is not None and self.open_price is not None:
                self.margin = self.qty * self.open_price / self.strategy.leverage
            return self.margin

        def get_liquidation_price(self):
            return (self.qty * self.open_price - (1 if self.long else -1) * self.margin) / (
                    (1 - (1 if self.long else -1) * (
                                self.strategy.maintenance_margin + self.strategy.taker_fee)) * self.qty)
        def equals(self,trade:'Strategy.Trade'):
            if self.open_price!=trade.open_price:return False
            if self.qty!=trade.qty:return False
            if self.long!=trade.long:return False
            return True


    class Order:
        def __init__(self, size, price:float=None, long=True, _type:Literal['limit','market']='market',stop=False, name=None,_time=None,_id=None,_margin=None):
            self.id = _id
            self.time = _time
            self.price= price
            self.size = size
            self.long = long
            self.type = _type
            self.stop = stop
            self.name = name
            self.margin = _margin

        def __str__(self):
            return f"{'Stop' if self.stop else self.type} order {'('+self.name+')' if self.name is not None else ''} : {'buy' if self.long else 'sell'} {self.size} @{self.price}"

        def check_order(self, candle):
            if self.stop:
                if self.long and candle['High'] > self.price:
                    return True
                if not self.long and candle['Low'] < self.price:
                    return True
            elif self.price is not None:
                if self.long and candle['Low'] < self.price:
                    return True
                if not self.long and candle['High'] > self.stop:
                    return True

        def equals(self,order:'Strategy.Order'):
            if self.price!=order.price:return False
            if self.size!=order.size:return False
            if self.long!=order.long:return False
            if self.stop!=order.stop:return False
            if self.id!=order.id:return False
            return True


def find_time_index_in_chronological(list_of_dict, time_in_second):
    if list_of_dict[0].get('Time') > list_of_dict[1].get('Time'):
        oldest = list_of_dict[-1].get('Time')
        newest = list_of_dict[0].get('Time')
    else:
        oldest = list_of_dict[0].get('Time')
        newest = list_of_dict[-1].get('Time')
    if time_in_second > newest or time_in_second < oldest:
        return None
    for index, value in enumerate(list_of_dict):
        if value.get('Time') == time_in_second:
            return index
    return None

def last_empty_index(list_of_dict,key):
    for index, value in enumerate(list_of_dict):
        if not key in value or value.get(key) == "None" or value.get(key) is None or value.get(key) == "" or value.get(key) == "nan":
            continue
        else:
            return index
    return len(list_of_dict)-1

