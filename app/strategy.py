
import threading
import time
import importlib
from datetime import datetime

import app.wip.models
from app.files_rw import config_update
from app.logging import app_logger, strategy_logger
from app.models import Candles


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
        self.name=""

    def run(self):
        app_logger.info("Received start signal : starting")
        if self.strategy is not None:
            try:
                self.candles = app.wip.models.Candles(self.strategy.api, self.strategy.symbol, self.strategy.timeframe, 100)
                self.candles.get_candles_history(self.strategy.min_bars_back,self.strategy.indicators)
                while True:
                    print("States_differ=",not self.check_state(self.get_platform_state()))
                    if self.stop_signal:
                        app_logger.info("Received stop signal : stopping")
                        break
                    config_update_action=self.strategy.update_config()
                    if config_update_action==2: #If strategy has reset, reset candles
                        del self.candles
                        self.candles = app.wip.models.Candles(self.strategy.api, self.strategy.symbol, self.strategy.timeframe, 100)
                        self.candles.get_candles_history(28, self.strategy.indicators)
                        lines_added=1
                    elif config_update_action==1: #if indicators need recalculation
                        self.candles.update_history(self.strategy.indicators)
                        #self.candles.calc_indicators(self.strategy.indicators)
                        lines_added=1
                    else:
                        lines_added=self.candles.update_history(self.strategy.indicators)
                    if lines_added>0:
                        try:
                            self.strategy.apply_strategy(self.candles,0)
                        except BaseException as exception:
                            strategy_logger.exception(exception)
                    time_to_wait=max(self.candles.history[0]['Time']+2*self.strategy.candle_duration-time.time(),0)
                    #print('last_history='+str(datetime.fromtimestamp(self.candles.history[0]['Time'])))
                    #print('min_time_to_fetch='+str(datetime.fromtimestamp(self.candles.history[0]['Time']+self.strategy.candle_duration)))
                    #print('current_time=' + str(datetime.fromtimestamp(time.time())))
                    #print('time to wait='+str(time_to_wait))
                    self.interrupt.wait(timeout=time_to_wait)
            except BaseException as exception:
                app_logger.exception(exception)
        else:
            app_logger.info("No strategy set : stopping")

    def stop(self):
        self.stop_signal=True


    def set_strategy(self,strategy_name,parameters,backtest=True):
        try:
            module = importlib.import_module('app.'+strategy_name)
            class_ = getattr(module, strategy_name+'Strategy')
            self.strategy = class_(parameters,backtest)
            state=self.get_platform_state()
            self.strategy.set_state(state)
            return
        except BaseException as exception:
            app_logger.exception(exception)

    import app.wip.models
    def backtest(self):
        if self.strategy is not None:
            try:
                candles=app.wip.models.Candles(self.strategy.api,self.strategy.symbol,self.strategy.timeframe,100)
                candles.prepare_backtest(self.strategy.start_date,self.strategy.indicators,self.strategy.min_bars_back)
                candles.get_backtest_candle()
                for index,candle in enumerate(candles.backtest_candles):
                    if len(candles.history)>1 and candle['Time'] >= self.strategy.start_date:
                        self.strategy.apply_strategy(candles,0)
                return self.strategy.strategy, candles

            except BaseException as exception:
                app_logger.exception(exception)
    '''
    def backtest(self):
        if self.strategy is not None:
            try:
                candles = Candles(self.strategy.api, self.strategy.symbol, self.strategy.timeframe,100,self.strategy.indicators)
                if candles.history[-1].get('Time')>self.strategy.start_date:
                    candles.increase_history(self.strategy.start_date,indicators=self.strategy.indicators)

                for index in reversed(range(len(candles.history))):
                    if candles.history[index]['Time'] < self.strategy.strategy.start_date or index==len(candles.history)-1: continue #loop till backtest starting time
                    self.strategy.apply_strategy(candles,index)

                return self.strategy.strategy,candles
            except BaseException as exception:
                app_logger.exception(exception)
    '''
    def get_platform_state(self):
        import copy
        platform_state=copy.deepcopy(self.strategy)
        platform_state.strategy.open_trades=[]
        platform_state.strategy.open_orders=[]
        current_position = platform_state.api.get_position(platform_state.symbol)
        open_orders = platform_state.api.get_open_orders(platform_state.symbol)
        # self.strategy.capital = current_position.pop('capital')
        if current_position:
            platform_state.strategy.last_known_price = current_position.pop('last_known_price')
            platform_state.strategy.log_trade(**current_position)
        if open_orders is not None:
            no_state = False
            for index, order in enumerate(open_orders):
                platform_state.strategy.log_order(order['price'], order['long'], order['qty'], None, order['stop'],
                                        order['id'])
        return platform_state

    def check_state(self,state):
        if self.strategy.strategy.position is None:
            if state.strategy.position is not None:
                print(1)
                return False
        elif state.strategy.position is None :
            print(2)
            return False
        elif not self.strategy.strategy.position.equals(state.strategy.position):
            print(3)
            return False
        if len(state.strategy.open_orders)!=len(self.strategy.strategy.open_orders):
            print(4)
            return False
        if len(state.strategy.open_orders)>0:
            for index,order in enumerate(self.strategy.strategy.open_orders.copy()):
                order.name=None
                if not state.strategy.open_orders[index].equals(order):
                    print('index=', index)
                    return False
        return True




