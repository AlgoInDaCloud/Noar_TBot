import threading
import time
import importlib
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
                self.candles = Candles(self.strategy.api, self.strategy.symbol, self.strategy.timeframe, 100, self.strategy.indicators)
                while True:
                    if self.stop_signal:
                        app_logger.info("Received stop signal : stopping")
                        break
                    if self.strategy.update_config(): #If strategy has reset, reset candles
                        self.candles = Candles(self.strategy.api, self.strategy.symbol, self.strategy.timeframe, 100,
                                               self.strategy.indicators)
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
            return
        except BaseException as exception:
            app_logger.exception(exception)

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







