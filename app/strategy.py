from datetime import datetime
import time
from threading import Thread
import importlib

from app.logging import app_logger, strategy_logger
from app.models import Candles


class Bot(Thread):
    def __init__(self, *args, **keywords):
        try:
            Thread.__init__(self, *args, **keywords)
        except BaseException as exception:
            app_logger.exception(exception)
        self.stop_signal=False
        self.parameters=None
        self.run_since=time.time()
        self.api=None
        self.strategy=None
        self.candles=None
        self.name=""

    def run(self):
        if self.strategy is not None:
            try:
                self.candles = Candles(self.api, self.strategy.symbol, self.strategy.timeframe, 100, self.strategy.indicators)
                candles_number=len(self.candles.history)
                while True:
                    if self.stop_signal:
                        print("stopping thread")
                        break
                    print('enterLoop')
                    self.candles.update_history(self.strategy.indicators)
                    if len(self.candles.history)>candles_number:
                        candles_number=len(self.candles.history)
                        try:
                            self.strategy.apply_strategy(self.candles,0)
                        except BaseException as exception:
                            strategy_logger.exception(exception)
                    time_to_wait=max(self.candles.history[0]['Time']+2*self.strategy.candle_duration-time.time(),0)
                    print('last_history='+str(datetime.fromtimestamp(self.candles.history[0]['Time'])))
                    print('min_time_to_fetch='+str(datetime.fromtimestamp(self.candles.history[0]['Time']+self.strategy.candle_duration)))
                    print('current_time=' + str(datetime.fromtimestamp(time.time())))
                    print('time to wait='+str(time_to_wait))
                    time.sleep(time_to_wait)
            except BaseException as exception:
                app_logger.exception(exception)

    def stop(self):
        self.stop_signal=True

    def set_strategy(self,strategy_name,parameters,backtest=True):
        try:
            module = importlib.import_module('app.'+strategy_name)
            class_ = getattr(module, strategy_name+'Strategy')
            self.strategy = class_(parameters,backtest)
            self.api = self.strategy.api
            return
        except BaseException as exception:
            app_logger.exception(exception)

    def backtest(self):
        if self.strategy is not None:
            try:
                candles = Candles(self.api, self.strategy.symbol, self.strategy.timeframe,100,self.strategy.indicators)
                if candles.history[-1].get('Time')>self.strategy.start_date:
                    candles.increase_history(self.strategy.start_date,indicators=self.strategy.indicators)

                for index in reversed(range(len(candles.history))):
                    if candles.history[index]['Time'] < self.strategy.strategy.start_date or index==len(candles.history)-1: continue #loop till backtest starting time
                    self.strategy.apply_strategy(candles,index)

                return self.strategy.strategy,candles
            except BaseException as exception:
                app_logger.exception(exception)







