import time
from datetime import datetime
from time import sleep
from typing import List, Dict, Literal
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import app
from app import login
from app.api import Api
import pandas as pd
import pandas_ta as pta
from app.files_rw import csv_to_dicts, dicts_to_csv, correct_types_from_strings
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
def load_user(id):
    return User()


class Candles:
    def __init__(self, api:Api, symbol, timeframe,min_bars_back=100,indicators=None):
        self.csv_file_path = "app/datas/"+symbol.replace("/", "").replace(":","_") + "_" + timeframe  #history_file
        self.api = api
        self.symbol = symbol
        self.timeframe = timeframe
        self.history = self.get_candles_history(min_bars_back,indicators)

    # Retrieve candle history until now

    def get_csv_history(self):
        history = csv_to_dicts(self.csv_file_path)
        history = correct_types_from_strings(history)
        return history

    def set_csv_history(self, new_lines=None):
        if new_lines is None:
            history = list(reversed(self.history))
            dicts_to_csv(history, self.csv_file_path, False)
        else:
            new_lines = list(reversed(new_lines))
            dicts_to_csv(new_lines, self.csv_file_path, True)

    def check_csv_history(self):
        history = csv_to_dicts(self.csv_file_path)
        history = correct_types_from_strings(history)
        bugs=0
        for index in range(len(history)):
            if index==0:continue
            if history[index]['Time']-history[index-1]['Time'] > self.timeframe_to_seconds(self.timeframe):
                bugs+=1
                print('Gap_found=',datetime.fromtimestamp(history[index-1]['Time']+1),datetime.fromtimestamp(history[index]['Time']))
                missing=self.get_history_api(int(history[index-1]['Time'])+1,int(history[index]['Time']))
                missing.reverse()
                for candle in missing:
                    history.insert(index,candle)
            if history[index]['Time']-history[index-1]['Time'] < self.timeframe_to_seconds(self.timeframe):
                bugs+=1
                print('Double_found=', datetime.fromtimestamp(history[index - 1]['Time']),
                      datetime.fromtimestamp(history[index]['Time']))
                history.pop(index)
        if bugs>0:
            print(bugs,'bugs found and corrected')
            dicts_to_csv(history,self.csv_file_path,False)
        else:
            print("No missing or doubled candle")


    def get_candles_history(self, min_bars_back,indicators):
        history = self.get_csv_history()
        if len(history) == 0:
            history = self.get_history_api(None, bars=min_bars_back,closed=True)
            history.reverse()
            self.history = history
            if indicators is not None:
                self.calc_indicators(indicators)
            self.set_csv_history()
        else:
            history.reverse()
            self.history = history
            self.update_history(indicators)
        #if indicators is not None:
        #    self.calc_indicators(indicators)
            '''
            if len(self.history)<min_bars_back:
                new_lines=self.get_history_api(None,self.history[-1].get('Time')-1,min_bars_back-len(self.history))
                new_lines.reverse()
                self.history.extend(new_lines)
                self.set_csv_history()
            '''
        return history

    def update_history(self,indicators=None):
        new_lines = self.get_history_api(int(self.history[0].get('Time')) + 1,closed=True)
        new_lines.reverse()
        lines_to_save=len(new_lines)
        self.history = new_lines + self.history
        self.calc_indicators(indicators)
        self.set_csv_history(list(self.history[:lines_to_save]))
        '''Recalculating partially causes imprecision
        new_lines=self.calc_rsi(new_lines,list(reversed(self.history)))
        new_lines.reverse()
        self.set_csv_history(new_lines)
        self.history=new_lines+self.history
        '''


    def increase_history(self, since=None, bars_back=None,indicators=None):
        print('initial_start=' + str(datetime.fromtimestamp(self.history[-1].get('Time'))))
        older_lines = self.get_history_api(since-1, int(self.history[-1].get('Time'))-1, bars_back)
        if len(older_lines) > 0:
            older_lines.reverse()
            self.history.extend(older_lines)
            self.calc_indicators(indicators,recalculate=True)
            self.set_csv_history()
        print('final_start=' + str(datetime.fromtimestamp(self.history[-1].get('Time'))))

    def get_history_api(self, since=None, until=None, bars=None, closed=True):
        timeframe_in_seconds = self.timeframe_to_seconds(self.timeframe)  # candle duration in seconds
        if until is None:
            until = time.time()
            if closed:
                until = until - until%timeframe_in_seconds -1 #Round to last closed candle
        lines_fetched = list()  #Initiate variable for API response

        max_delay = timeframe_in_seconds - 1  #Max delay with same candle
        candles_to_fetch = bars if bars is not None else int((until - since) / timeframe_in_seconds)  #Number of candles to fetch
        if candles_to_fetch == 0:
            return lines_fetched
        since = int(since) if since is not None else int(until - bars * timeframe_in_seconds)
        while since + max_delay < until:
            print("Since=", datetime.fromtimestamp(since), "Until=", datetime.fromtimestamp(until), "Candles=",
                  candles_to_fetch)
            new_lines = self.api.get_ohlc(self.symbol, self.timeframe, since=since,until=until,limit=(candles_to_fetch if candles_to_fetch < 1000 else 1000))
            lines_fetched[:0] = new_lines
            candles_to_fetch -= len(new_lines)
            if len(new_lines) == 0 or candles_to_fetch==0: break
            print("NL=", len(new_lines),datetime.fromtimestamp(new_lines[0].get('Time')),
                  datetime.fromtimestamp(new_lines[-1].get('Time')))
            until = int(lines_fetched[0].get('Time'))
            sleep(1)
        if len(lines_fetched) > 0:
            print("fetched=",datetime.fromtimestamp(lines_fetched[0].get('Time')),
                  datetime.fromtimestamp(lines_fetched[-1].get('Time')))
        else:
            print("no lines fetched")
        return lines_fetched

    def calc_indicators(self, indicators: Dict, since=None,recalculate=False):
        if 'RSI' in indicators:
            if since is None and not recalculate:
                last_empty = last_empty_index(self.history, 'RSI')
                since_empty=self.history[last_empty]['Time']
                print('RSI_since=',datetime.fromtimestamp(since_empty))
            self.calc_rsi(length=indicators['RSI'], since=since)
        if 'PivotsHL' in indicators:
            if since is None and not recalculate:
                last_empty = last_empty_index(self.history, 'Pivot')
                since_empty=self.history[last_empty]['Time']
                print('Pivot_since=',datetime.fromtimestamp(since_empty))

            self.calc_pivots_hl(bars=indicators['PivotsHL'],since=since)
        return

    def calc_rsi(self, length=14, since=None):
        if since is not None:
            since_index = find_time_index_in_chronological(self.history, since)
            lines_for_calculation = list(self.history[0:since_index + length])
        else:
            since_index = len(self.history)
            lines_for_calculation = list(self.history)
        lines_for_calculation.reverse()  #Set chronological
        dataframe = {'Close': [d.get('Close') for d in lines_for_calculation if 'Close' in d]}
        dataframe = pd.DataFrame(data=dataframe)
        rsi = round(pta.rsi(dataframe['Close'], length=length), 2)
        rsi = list(rsi[length - 1:])  #remove lines not calculated
        rsi.reverse()
        for index in range(since_index):
            if index in range(-len(rsi), len(rsi)):
                self.history[index]['RSI'] = float(rsi[index])
            else:
                self.history[index].setdefault('RSI', None)

    def calc_pivots_hl(self, bars=10, since=None):
        if since is not None:
            since_index = find_time_index_in_chronological(self.history, since)
            #if len(self.history) - 1 > since_index + bars:
                #lines_for_calculation = list(self.history[0:since_index + bars])
            #else:
                #lines_for_calculation = list(self.history)
            if len(self.history) - 1 > since_index + 1 and 'Pivot' in self.history[since_index + 1]:
                pivots = self.history[since_index + 1]['Pivot']
            else:
                pivots = {'high': None, 'low': None}
        else:
            since_index = len(self.history) - 1
            #lines_for_calculation = self.history
            pivots = {'high': None, 'low': None}
        highs = list()
        lows = list()
        #lines_for_calculation.reverse()
        for index in range(since_index, -1, -1):
            if len(highs) < (2 * bars + 1):
                highs.append(self.history[index]['High'])
                lows.append(self.history[index]['Low'])
            else:
                highs.append(self.history[index]['High'])
                lows.append(self.history[index]['Low'])
                highs.pop(0)
                lows.pop(0)
                if highs[10] == max(highs):
                    pivots['high'] = highs[10]
                elif lows[10] == min(lows):
                    pivots['low'] = lows[10]
                if pivots['low'] is not None and pivots['low']>self.history[index]['Low']:
                    pivots['low']=None
                if pivots['high'] is not None and pivots['high']<self.history[index]['High']:
                    pivots['high']=None
            self.history[index]['Pivot'] = dict(pivots)

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
            parameters = csv_to_dicts(parameter_file)
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

    def open_trade(self, open_time, open_price, long, qty, _name=None,margin=None):
        try:
            response=self.api.send_order(self.symbol, 'buy' if long else 'sell', qty, 'market')
            self.log_trade(open_time,response['price'],response['long'],response['size'],_name)
            '''
            position = get_position(self.exchange, self.symbol)
            margin=position['initialMargin']
            contracts=position['contracts']#QTY / Size
            price=position['entryPrice']
            maintenance_margin_percent=position['maintenanceMarginPercentage']
            leverage=position['leverage']
            side=position['side'] # "long" or "short" (strings)
            '''
        except BaseException as exception:
            strategy_logger.exception(exception)



    def log_trade(self,open_time, open_price, long, qty, name=None,margin=None):
        self.open_trades.append(Strategy.Trade(self, open_time, open_price, long, qty, open_name=name,margin=margin))
        self.set_position()

    def open_order(self,_price,_long,_qty,_name=None,_stop=False):
        try:
            response = self.api.send_order(self.symbol, 'buy' if _long else 'sell', _qty,'limit', _price,_stop)
            self.log_order(response['price'],response['long'],response['size'],_name,_stop,response['id'])
            return response
            '''
            orders = get_open_orders(self.exchange, self.symbol)
            for order in orders:
                id=order['id']
                time=order['timestamp']
                side=order['side'] # 'buy' or 'sell'
                price=order['price']
                size=order['amount'] # in base coin
                filled=order['filled']
                remaining=order['remaining']
                trigger_price=order['triggerPrice']
                stop_loss_price=order['takeProfitPrice']
                stop_price=order['stopPrice']
            '''
        except BaseException as exception:
            strategy_logger.exception(exception)

    def log_order(self,_price,_long,_qty,_name=None,_stop=False,_id=None):
        self.open_orders.append(self.Order(_qty, _price, _long, _stop, _name,_id))

    def edit_order(self,_id,_price,_long,_size,_stop,_symbol,_type:Literal['limit','market']='limit'):
        try:
            response=self.api.edit_order(_id,_symbol,'buy' if _long else 'sell',_size,_price,_type,_stop)
            self.edit_log_order(response['id'],response['price'], response['long'], response['size'], _stop)
        except BaseException as exception:
            strategy_logger.exception(exception)

    def edit_log_order(self,_id,_price,_long,_size,_stop,_symbol):
        for index in range(len(self.open_orders)):
            if self.open_orders[index].id == _id:
                self.open_orders[index].limit=_price
                self.open_orders[index].long = _long
                self.open_orders[index].qty = _size
                self.open_orders[index].stop = _stop


    def cancel_orders(self,_id=None):
        if _id is None:
            cancels = self.api.cancel_all_order(self.symbol)
            for cancel in cancels:
                if "id" in cancel:
                    self.remove_log_orders(cancel['id'])
        else:
            cancel = self.api.cancel_order(_id,self.symbol)
            if "id" in cancel:
                self.remove_log_orders(cancel['id'])

    def remove_log_orders(self,_id=None):
        if id is None:
            self.open_orders=[]
        else:
            for order in self.open_orders.copy():
                if order.id==_id:
                    self.open_orders.remove(order)

    def close_order(self, close_time, qty, name=None,price=None):
        if self.position is not None:
            try:
                response = self.api.send_order(self.symbol, 'sell' if self.position.long else 'buy', qty, 'market')
                self.log_close_order(close_time,response['size'],name,response['avg_price'])
            except BaseException as exception:
                strategy_logger.exception(exception)


    def log_close_order(self,close_time, qty, name=None,close_price=None):
        qty_left = qty
        while qty_left > 0 and len(self.open_trades) > 0:
            trade = self.open_trades.pop(0)
            qty_left = trade.close_trade(close_time, close_price, qty)
            if qty_left < 0:
                self.open_trades.insert(0, Strategy.Trade(self, trade.open_time, trade.open_price, trade.long,
                                                          abs(qty_left), open_name=trade.open_name))
            trade.close_name = name
            self.closed_trades.append(trade)
        self.set_position()


    def check_orders(self, candle):
        orders_filled = []

        for index, order in enumerate(self.open_orders):
            #trade_logger.info('Order: '+order.name+' '+str(order.limit)+' '+str(order.long)+' '+str(order.stop)+' '+str(order.qty))
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


        def close_trade(self, time, price, qty):
            self.close_price = price
            self.close_time = time
            # If trade bigger, reduce to order qty and return qty left in trade
            close_qty_left = qty - self.qty
            if close_qty_left > 0:
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

    class Order:
        def __init__(self, qty, limit:float=None, long=True, stop=False, name=None,id=None):
            self.id=id
            self.limit = limit
            self.qty = qty
            self.long = long
            self.stop = stop
            self.name = name

        def check_order(self, candle):
            if self.stop:
                if self.long and candle['High'] > self.limit:
                    return True
                if not self.long and candle['Low'] < self.limit:
                    return True
            elif self.limit is not None:
                if self.long and candle['Low'] < self.limit:
                    return True
                if not self.long and candle['High'] > self.stop:
                    return True


def find_time_index_in_chronological(list_of_dict, time_in_second):
    if list_of_dict[0].get('Time') > list_of_dict[1].get('Time'):
        chron = False
        oldest = list_of_dict[-1].get('Time')
        newest = list_of_dict[0].get('Time')
    else:
        chron = True
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

