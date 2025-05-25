import datetime
import re
import threading
import time
import importlib
import copy

from app import app
from app.files_rw import save_state, restore_state, read_config_file, write_config_file,CsvRW
from app.models import Candles
from app.logging import app_logger, strategy_logger
from config import BOTS_STATES


class Bot(threading.Thread):
    def __init__(self, *args, **keywords):
        try:
            threading.Thread.__init__(self, *args, **keywords)
        except BaseException as exception:
            app_logger.exception(exception)
        self.stop_signal=False
        self.parameter_file=None
        self.run_since=time.time()
        self.interrupt=threading.Event()
        self.strategy=None
        self.candles=None
        #self.name=keywords['name'] if 'name' in keywords else ""
        res = re.search(r"(\w+)-bot(\d+)", self.name)
        self.strategy_name = res.group(1)
        self.strategy_id = res.group(2)
        self.state_file=f"app/datas/strategies/{self.strategy_name}/{self.strategy_id}/state"


    def run(self):
        app_logger.info("Received start signal : starting")
        if self.strategy is not None:
            try:
                self.register()
                self.candles = Candles(self.strategy.api, self.strategy.symbol, self.strategy.timeframe, 100)
                self.candles.get_candles_history(self.strategy.min_bars_back,self.strategy.indicators)
                while True:
                    if self.stop_signal:
                        app_logger.info("Received stop signal : stopping")
                        break
                    config_update_action=self.strategy.update_config()
                    if config_update_action==2: #If strategy has reset, reset candles
                        del self.candles
                        self.candles = Candles(self.strategy.api, self.strategy.symbol, self.strategy.timeframe, 100)
                        self.candles.get_candles_history(28, self.strategy.indicators)
                        lines_added=1
                    elif config_update_action==1: #if indicators need recalculation
                        self.candles.calc_indicators(self.strategy.indicators)
                        self.candles.update_history(self.strategy.indicators) 
                        lines_added=1
                    else:
                        lines_added=self.candles.update_history(self.strategy.indicators)
                    if lines_added>0:
                        try:
                            self.strategy.update_filled_orders(self.candles.history[0])
                            if not self.check_state(self.get_platform_state()):
                                raise self.MisalignmentError("Bot state differs from platform's. Stopping bot")
                            self.strategy.apply_strategy(self.candles,0)
                            self.save_state()
                        except self.MisalignmentError as exception:
                            app_logger.error(exception)
                            self.stop()
                            raise
                        except BaseException as exception:
                            strategy_logger.exception(exception)
                    time_to_wait=max(self.candles.history[0]['Time']+2*self.strategy.candle_duration-time.time(),0)
                    time_to_wait=min(time_to_wait,self.strategy.api.fetch_next_funding(self.strategy.symbol)) #synchronize for next funding time
                    self.interrupt.wait(timeout=time_to_wait)
            except BaseException as exception:
                app_logger.exception(exception)
        else:
            app_logger.info("No strategy set : stopping")

    def stop(self):
        self.unregister()
        self.stop_signal=True

    def set_strategy(self,strategy_name,parameters,backtest=True):
        try:
            module = importlib.import_module('app.strategies.'+strategy_name)
            class_ = getattr(module, strategy_name+'Strategy')
            self.strategy = class_(parameters,backtest)
            if not backtest:
                state=self.get_platform_state()
                if self.check_state(state):
                    app_logger.info('Platform has no current state : starting fresh !')
                else:
                    app_logger.warning("Platform has current state : updating bot state to match platform's, this may cause errors !")
                    self.strategy.set_state(state)
            return
        except BaseException as exception:
            app_logger.exception(exception)

    def backtest(self):
        if self.strategy is not None:
            try:
                candles= Candles(self.strategy.api, self.strategy.symbol, self.strategy.timeframe, 100)
                candles.prepare_backtest(self.strategy.start_date,self.strategy.indicators,self.strategy.min_bars_back)
                candles.get_backtest_candle()
                for index,candle in enumerate(candles.backtest_candles):
                    if len(candles.history)>1 and candle['Time'] >= self.strategy.start_date:
                        self.strategy.update_filled_orders(candle)
                        self.strategy.apply_strategy(candles,0)
                return self.strategy.strategy, candles

            except BaseException as exception:
                app_logger.exception(exception)
        return None

    def get_platform_state(self):
        import copy
        platform_state=copy.deepcopy(self.strategy)
        platform_state.strategy.open_trades=[]
        platform_state.strategy.open_orders=[]
        platform_state.strategy.position=None
        current_position = platform_state.api.get_position(platform_state.symbol)
        open_orders = platform_state.api.get_open_orders(platform_state.symbol)
        # self.strategy.capital = current_position.pop('capital')
        if current_position:
            platform_state.strategy.last_known_price = current_position.pop('last_known_price')
            platform_state.strategy.open_order(platform_state.strategy.Order(current_position['size'], current_position['open_price'], current_position['long'], 'market',False, 'Fetched_position',current_position['open_time'],None,current_position['margin']),True)
        if open_orders is not None:
            for index, order in enumerate(open_orders):
                platform_state.strategy.open_order(platform_state.strategy.Order(order['size'],order['price'], order['long'],'market' if order['stop'] else 'limit', order['stop'], 'Fetched_order', _id=order['id']),True)
        return platform_state

    def check_state(self,state):
        strategy_logger.info(f"{state.strategy.__dict__}")
        if self.strategy.strategy.position is None:
            if state.strategy.position is not None:
                strategy_logger.warning('Currently holding position on platform')
                return False
        elif state.strategy.position is None :
            strategy_logger.warning('Not holding position on platform')
            return False
        elif not self.strategy.strategy.position.equals(state.strategy.position):
            stri=""
            if self.strategy.strategy.position.long!=state.strategy.position.long:stri+="long differ,"
            if self.strategy.strategy.position.drawdown_price!=state.strategy.position.drawdown_price:stri+="dd differ,"
            if self.strategy.strategy.position.runup_price!=state.strategy.position.runup_price:stri+="ru differ,"
            if self.strategy.strategy.position.strategy!=state.strategy.position.strategy:stri+="strat differ,"
            if self.strategy.strategy.position.id!=state.strategy.position.id:stri+="id differ,"
            if self.strategy.strategy.position.open_time!=state.strategy.position.open_time:stri+="time differ,"
            if self.strategy.strategy.position.open_price!=state.strategy.position.open_price:stri+="price differ,"
            if self.strategy.strategy.position.close_price!=state.strategy.position.close_price:stri+="cprice differ,"
            if self.strategy.strategy.position.close_time!=state.strategy.position.close_time:stri+="ctime differ,"
            if self.strategy.strategy.position.close_name!=state.strategy.position.close_name:stri+="cname differ,"
            if self.strategy.strategy.position.qty!=state.strategy.position.qty:
                stri+="size differ,"
                strategy_logger.info(f"bot={self.strategy.strategy.position.qty}, platform={state.strategy.position.qty}")
            if self.strategy.strategy.position.open_name!=state.strategy.position.open_name:stri+="name differ,"
            if self.strategy.strategy.position.margin!=state.strategy.position.margin:stri+="margin differ"
            strategy_logger.warning(f'Positions differ:{stri}')
            return False
        if len(state.strategy.open_orders)!=len(self.strategy.strategy.open_orders):
            strategy_logger.warning('Number of orders differ')
            return False
        if len(state.strategy.open_orders)>0:
            for index,order in enumerate(copy.deepcopy(self.strategy.strategy.open_orders)):
                order.name=None
                state.strategy.open_orders[index].name=None
                if not state.strategy.open_orders[index].equals(order):
                    strategy_logger.warning('Order differ')
                    strategy_logger.info(f"{order}")
                    strategy_logger.info(f"{state.strategy.open_orders[index]}")
                    stri=""
                    if order.id!=state.strategy.open_orders[index].id:stri+="id differ,"
                    if order.time!=state.strategy.open_orders[index].time:stri+="time differ,"
                    if order.price!=state.strategy.open_orders[index].price:stri+="price differ,"
                    if order.size!=state.strategy.open_orders[index].size:stri+="size differ,"
                    if order.long!=state.strategy.open_orders[index].long:stri+="long differ,"
                    if order.stop!=state.strategy.open_orders[index].stop:stri+="stop differ,"
                    if order.type!=state.strategy.open_orders[index].type:stri+="type differ,"
                    if order.name!=state.strategy.open_orders[index].name:stri+="long differ,"
                    if order.margin!=state.strategy.open_orders[index].margin:stri+="margin differ"
                    strategy_logger.info(f"{stri}")
                    return False
        return True

    def save_state(self):
        save_state(self.state_file,self)

    def register(self):
        if self.strategy.name not in BOTS_STATES['RUNNING']:
            BOTS_STATES['RUNNING'][self.strategy_name]=[self.strategy_id]
        elif self.strategy_id not in BOTS_STATES['RUNNING'][self.strategy_name]:
            BOTS_STATES['RUNNING'][self.strategy_name].append(self.strategy_id)
        write_config_file('app/params/bots.ini',BOTS_STATES)
    def unregister(self):
        if self.strategy.name not in BOTS_STATES['HISTORY']:
            BOTS_STATES['HISTORY'][self.strategy_name]=[self.strategy_id]
        BOTS_STATES['RUNNING'][self.strategy_name].remove(self.strategy_id)
        write_config_file('app/params/bots.ini', BOTS_STATES)

    class MisalignmentError(Exception):
        pass

    def __getstate__(self):
        return {
            'parameter_file':self.parameter_file,
            'run_since':self.run_since,
            'strategy': self.strategy,
            'candles':self.candles,
            'name':self.name,
            'strategy_name':self.strategy_name,
            'strategy_id':self.strategy_id,
            'state_file':self.state_file
        }
    def __setstate__(self, state):
        self.__init__(name=state['name'])
        self.parameter_file=state['parameter_file']
        self.run_since=state['run_since']
        self.strategy=state['strategy']
        self.candles=state['candles']
        self.name=state['name']
        self.strategy_name=state['strategy_name']
        self.strategy_id=state['strategy_id']
        self.state_file=state['state_file']

from sklearn.neural_network import MLPRegressor
import numpy as np
import random
import os
class Optimizer(threading.Thread):

    def __init__(self, *args, **keywords):
        try:
            threading.Thread.__init__(self,name=keywords['name'])
        except BaseException as exception:
            app_logger.exception(exception)
        self.stop_signal=False
        self.parameters=keywords['parameters']
        self.run_since=time.time()
        self.interrupt=threading.Event()
        self.strategy=None
        self.backtests=list(dict())

    def range_float(self, start, stop, step):
        x = start
        while x <= stop:
            yield x
            x += step

    def run(self):
        app_logger.info("Received start signal : optimizer starting")
        params = {
            'api': self.parameters['api'],
            'symbol': self.parameters['symbol'],
            'timeframe': self.parameters['timeframe'],
            'initial_capital': self.parameters['initial_capital'],
            'start_date': self.parameters['start_date'],
            'rsi_ob': self.parameters['rsi_ob']
        }
        martingale_number = [i for i in range(self.parameters['martingale_number_min'], self.parameters['martingale_number_max']+1, 1)]
        leverage = [i for i in range(self.parameters['leverage_min'], self.parameters['leverage_max']+1, 2)]
        pivot_width = [i for i in range(self.parameters['pivot_width_min'], self.parameters['pivot_width_max']+1, 2)]
        tp_qty_percent = [i for i in range(self.parameters['tp_qty_percent_min'], self.parameters['tp_qty_percent_max']+1, 2)]
        profit_sl_activation = [i for i in self.range_float(self.parameters['profit_sl_activation_min'], self.parameters['profit_sl_activation_max'] + 1, 1)]
        dist_btw_tp = [i for i in self.range_float(self.parameters['dist_btw_tp_min'], self.parameters['dist_btw_tp_max']+1, 2)]
        rsi_length = [i for i in range(self.parameters['rsi_length_min'], self.parameters['rsi_length_max']+1, 1)]
        rsi_os = [i for i in range(self.parameters['rsi_os_min'], self.parameters['rsi_os_max']+1, 2)]

        max_iter = 10000
        tested_parameters = []

        backtest_writer = CsvRW('app/datas/strategies/martingale/optimizer/'+params['symbol']+'_'+params['timeframe']+'_'+params['start_date'].strftime('%Y-%m-%d %H:%M:%S')+'.log')
        backtest_writer.read_normal()
        neural_net = MLPRegressor(solver='lbfgs', max_iter=10000)
        var_params = {}
        row = {}

        for csv_line in backtest_writer.readline:
            self.backtests.append(csv_line.copy())
            Y = np.array([csv_line.pop('pnl')])
            csv_line.pop('drawdown')
            X = np.array([[value for value in csv_line.values()]])
            neural_net.partial_fit(X[0:1], Y[0:1])
            tested_parameters.append(''.join(str(value) for value in csv_line.values()))
        if os.stat(backtest_writer.csv_file_path).st_size == 0:
            keys = ['martingale_number', 'leverage', 'pivot_width', 'tp_qty_percent', 'profit_sl_activation',
                    'dist_btw_tp', 'rsi_length', 'rsi_os', 'pnl', 'drawdown']
        else:
            keys = None

        backtest_writer.write_to_csv('a', keys)
        var_params = {}
        row = {}


        def set_random_params():
            var_params['martingale_number'] = martingale_number[random.randrange(len(martingale_number))]
            var_params['leverage'] = leverage[random.randrange(len(leverage))]
            var_params['pivot_width'] = pivot_width[random.randrange(len(pivot_width))]
            var_params['tp_qty_percent'] = tp_qty_percent[random.randrange(len(tp_qty_percent))]
            var_params['profit_sl_activation'] = profit_sl_activation[random.randrange(len(profit_sl_activation))]
            var_params['dist_btw_tp'] = dist_btw_tp[random.randrange(len(dist_btw_tp))]
            var_params['rsi_length'] = rsi_length[random.randrange(len(rsi_length))]
            var_params['rsi_os'] = rsi_os[random.randrange(len(rsi_os))]
            identifier = ''.join(str(value) for value in var_params.values())
            return var_params, identifier

        for i in range(max_iter):
            if self.stop_signal:
                app_logger.info("Received stop signal : stopping")
                backtest_writer.close_if_open()
                break
            print('set_params')
            var_params, identifier = set_random_params()
            while identifier in tested_parameters:
                var_params, identifier = set_random_params()
            print(len(tested_parameters))
            params.update(var_params)
            tested_parameters.append(identifier)
            optimizer = Bot(name='martingale-bot0')
            optimizer.set_strategy('Martingale', params)
            print('backtest')
            backtest_strategy, candles = optimizer.backtest()
            print('save results')
            results = {'pnl': backtest_strategy.get_profit(),
                       'drawdown': backtest_strategy.max_drawdown}
            row.update(var_params)
            row.update(results)
            backtest_writer.write_line(list(row.values()))
            self.backtests.append(row)
            print('calc_neural')
            X = np.array([[value for value in var_params.values()]])
            Y = np.array([results['pnl']])
            neural_net.partial_fit(X[0:1], Y[0:1])
            print(neural_net.predict(X), results['pnl'])
            print(neural_net.loss_)

    def stop(self):
        self.stop_signal = True
