import threading
import time
import importlib
import copy
from datetime import datetime

from app.models import Candles
from app.logging import app_logger, strategy_logger


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
                        except self.MisalignmentError as exception:
                            app_logger.error(exception)
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
        self.stop_signal=True


    def set_strategy(self,strategy_name,parameters,backtest=True):
        try:
            module = importlib.import_module('app.'+strategy_name)
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
                        self.strategy.apply_strategy(candles,0)
                return self.strategy.strategy, candles

            except BaseException as exception:
                app_logger.exception(exception)

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
            platform_state.strategy.open_order(platform_state.strategy.Order(current_position['size'], current_position['open_price'], current_position['long'], 'market',False, 'Fetched_position',current_position['open_time'],None,current_position['margin']),True)
        if open_orders is not None:
            for index, order in enumerate(open_orders):
                platform_state.strategy.open_order(platform_state.strategy.Order(order['size'],order['price'], order['long'],'market' if order['stop'] else 'limit', order['stop'], 'Fetched_order', _id=order['id']),True)
        return platform_state

    def check_state(self,state):
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



    class MisalignmentError(Exception):
        pass
