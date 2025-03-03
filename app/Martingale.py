from datetime import datetime
from app.api import Api
from app.files_rw import config_update
from app.logging import trade_logger
from app.models import Strategy, Candles

class MartingaleStrategy:
    def __init__(self,parameters,_backtest=False):
        #Get parameters
        self.param_last_modified = None
        self.platform_api=parameters['api']
        self.symbol=parameters['symbol']
        self.timeframe=parameters['timeframe']
        self.martingale_number=int(parameters['martingale_number'])
        self.initial_capital = int(parameters['initial_capital'])
        self.leverage=int(parameters['leverage'])
        self.start_date=parameters['start_date'].timestamp()
        self.tp_qty_percent=int(parameters['tp_qty_percent'])/100
        self.profit_sl_activation=float(parameters['profit_sl_activation'])/100
        self.dist_btw_tp=float(parameters['dist_btw_tp'])/100
        self.indicators = {'RSI': int(parameters['rsi_length']), 'PivotsHL': int(parameters['pivot_width'])}
        self.rsi_trade_levels={'buy':int(parameters['rsi_os']),'sell':int(parameters['rsi_ob'])}
        self.candle_duration = Candles.timeframe_to_seconds(self.timeframe)
        self.min_bars_back=100 #Min candles history to have relevant signals
        self.backtest=_backtest

        #Set objects
        self.api=Api(self.platform_api)
        self.strategy=Strategy(None,self.initial_capital,self.leverage,start_date=self.start_date,api=self.api,symbol=self.symbol)

        #Initialize variables
        self.stop_loss_price = None
        self.close_qty=0
        self.last_close_price = 0


    def apply_strategy(self,candles:Candles,current_index=0):
        self.strategy.last_known_price = candles.history[current_index]['Close']
        self.strategy.set_runup_drawdown(candles.history[current_index])
        if self.strategy.position is None:
            if self.trade_condition(candles.history[current_index],candles.history[current_index+1]):
                amount_per_order = self.strategy.get_equity() * self.strategy.leverage / (
                            self.martingale_number + 1)  # Funds available per order
                qty = amount_per_order / candles.history[current_index]['Close']
                qty = qty - qty % self.strategy.min_qty # Qty => round to min qty
                if qty > 0:  # If enough, set trade, martingale orders and liquidation price
                    candles.history[current_index]['Trade'] = "Entry"
                    self.launch_martingale(candles.history[current_index]['Time'], candles.history[current_index]['Close'], True,
                                      amount_per_order, qty)
                    self.close_qty = self.strategy.open_trades[-1].qty * self.tp_qty_percent  # Calculate TP qty
                    self.close_qty = self.close_qty - self.close_qty % self.strategy.min_qty
                else:
                    trade_logger.warning("Error:Not enough capital for trading")
        else:  # If in trade, check if TP, martingales ou SL orders have been triggered, and update runups/drawdowns
            if self.stop_loss_price is None or self.stop_loss_price == 0:  # if still in martingale phase
                if self.stop_loss_price is None and candles.history[current_index]['Close'] > self.strategy.position.open_price * (
                        1 + self.profit_sl_activation):
                    trade_logger.info('SL activation')
                    self.stop_loss_price = 0  # activate SL calculation if price rise above parameter

                if self.stop_loss_price == 0 and candles.history[current_index]['PivotsHL']['low'] is not None and candles.history[current_index]['PivotsHL']['low'] > self.strategy.position.open_price:  # If pivot in profit, activate SL and deactivate the rest
                    self.strategy.cancel_orders()
                    self.stop_loss_price = candles.history[current_index]['PivotsHL']['low']
                    self.strategy.open_order(self.strategy.Order(self.strategy.position.qty,self.stop_loss_price, not self.strategy.position.long,'market',True,'SL',candles.history[current_index]['Time']),self.backtest)
                    trade_logger.info(f"SL : {datetime.fromtimestamp(candles.history[current_index]['Time'])} Sell {self.strategy.position.qty} @ {self.stop_loss_price}")

            if self.close_qty>0 and self.tp_condition(candles.history[current_index], candles.history[current_index + 1]):  # Check for signal and if enough funds for tp
                    self.strategy.close_order(self.strategy.Order(self.close_qty,candles.history[current_index]['Close'],not self.strategy.position.long,'market',False,'TP',int(candles.history[current_index]['Time'])),self.backtest)
                    candles.history[current_index]['Trade'] = "TP"
                    trade=self.strategy.closed_trades[-1]
                    trade_logger.info(f"TP : {datetime.fromtimestamp(int(candles.history[current_index]['Time']))} Sell {trade.qty} @{trade.close_price} /{self.close_qty},{candles.history[current_index]['Close']}")
                    self.last_close_price=candles.history[current_index]['Close']
                    if self.strategy.position is None:
                        self.strategy.open_orders=[]
                        self.last_close_price=0
                        self.close_qty=0
                        self.stop_loss_price=None

            orders_filled = self.strategy.check_orders(candles.history[current_index])
            for order in orders_filled:
                order.time = candles.history[current_index]['Time']

                trade_logger.info(f"{order.name} order filled : {datetime.fromtimestamp(order.time)} {'Buy' if order.long else 'Sell'} {order.size} @{order.price}")
                if order.stop:
                    self.strategy.close_order(self.strategy.Order(order),True) # Only log the transaction
                    candles.history[current_index]['Trade'] = "SL"
                    self.last_close_price = 0
                    self.stop_loss_price = None
                    self.strategy.liquidation_price=None
                elif order.price is not None:
                    order.type='market'
                    self.strategy.open_order(order,True)
                    candles.history[current_index]['Trade'] = "Mart"

            if self.strategy.position is not None and candles.history[current_index]['Low'] < self.strategy.position.get_liquidation_price():  # if liquidated...sorry dude
                trade_logger.info('Liquidation')
                order=self.strategy.Order(self.strategy.position.qty,self.strategy.position.get_liquidation_price(),not self.strategy.position.long,'market',False,'Liquidation',candles.history[current_index]['Time'])
                self.strategy.close_order(order,True) # Only log the transaction
                self.last_close_price = 0  # reset variables
                self.stop_loss_price = None
            if (self.stop_loss_price is not None and self.stop_loss_price > 0
                    and candles.history[current_index]['PivotsHL']['low'] is not None and candles.history[current_index]['PivotsHL']['low']>self.stop_loss_price):
                trade_logger.info('Editing SL')
                order=self.strategy.open_orders[0]
                order.price=candles.history[current_index]['PivotsHL']['low']
                self.strategy.edit_order(order,self.backtest)
        return

    def launch_martingale(self, time, _initial_price, _long, _amount_per_order, _initial_qty, _security=0.005):
        temp_strategy = Strategy(leverage=self.strategy.leverage,
                                 taker_fee=self.strategy.taker_fee)
        order=self.strategy.Order(_initial_qty,_initial_price,_long,'market',False,'Entry',time)
        self.strategy.open_order(order,self.backtest)
        temp_strategy.open_order(order,True)
        trade=self.strategy.open_trades[-1]
        trade_logger.info(f"Entry : {datetime.fromtimestamp(trade.open_time)} {'buy'if trade.long else 'sell'} {trade.qty} @{trade.open_price}")
        order.type='limit'
        for i in range(self.martingale_number):
            order.price = temp_strategy.position.get_liquidation_price() * (1 + _security)
            order.size = round(_amount_per_order / order.price, 4)
            order.name = "Mart" + str(i+1) + "/" + str(self.martingale_number)
            self.strategy.open_order(order,self.backtest)
            temp_strategy.open_order(order,True)
            trade_logger.info(f"Mart{i+1} : {datetime.fromtimestamp(order.time)} {'buy' if order.long else 'sell'} {order.size} @{order.price}")
        self.strategy.liquidation_price=temp_strategy.position.get_liquidation_price()
        del temp_strategy


    def trade_condition(self,candle, prev_candle):
        if not 'RSI' in prev_candle or prev_candle.get('RSI') is None: return None
        if candle.get('RSI') > self.rsi_trade_levels['buy'] > prev_candle.get('RSI'):
            return True
        elif candle.get('RSI') < self.rsi_trade_levels['sell'] < prev_candle.get('RSI'):
            return False
        else:
            return None

    def tp_condition(self, candle, prev_candle):
        if (self.trade_condition(candle, prev_candle) == False
                and self.close_qty > 0
                and candle.get('Close') > self.strategy.position.open_price
                and ( self.last_close_price == 0 or candle['Close'] > self.last_close_price * (1 + self.dist_btw_tp ))):
            return True
        else:
            return False

    def update_config(self):
        last_modified,parameters=config_update('app/params/martingale.ini',self.param_last_modified)
        self.param_last_modified = last_modified
        return_value=0 # return 0 if config modification doesn't necessitate particular action (recalculation...)
        if parameters is not None:
            if 'PARAMETERS' in parameters:
                parameters = parameters['PARAMETERS']
            else:
                return False
            self.martingale_number = int(parameters['martingale_number'])
            self.initial_capital = int(parameters['initial_capital'])
            self.leverage = int(parameters['leverage'])
            self.start_date = parameters['start_date'].timestamp()
            self.tp_qty_percent = int(parameters['tp_qty_percent']) / 100
            self.profit_sl_activation = float(parameters['profit_sl_activation']) / 100
            self.dist_btw_tp = float(parameters['dist_btw_tp']) / 100
            if self.indicators != {'RSI': int(parameters['rsi_length']), 'PivotsHL': int(parameters['pivot_width'])}:
                self.indicators = {'RSI': int(parameters['rsi_length']), 'PivotsHL': int(parameters['pivot_width'])}
                return_value=1 #if indicator changes, return 1 to recalculate
            self.rsi_trade_levels = {'buy': int(parameters['rsi_os']), 'sell': int(parameters['rsi_ob'])}
            # If global changes, reset all
            if self.platform_api != parameters['api'] \
                    or self.symbol != parameters['symbol'] \
                    or self.timeframe != parameters['timeframe']:
                self.platform_api = parameters['api']
                self.symbol = parameters['symbol']
                self.timeframe = parameters['timeframe']
                self.candle_duration = Candles.timeframe_to_seconds(self.timeframe)
                # Set objects
                self.api = Api(self.platform_api)
                self.strategy = Strategy(None, self.initial_capital, self.leverage, start_date=self.start_date,
                                         api=self.api, symbol=self.symbol)
                # Initialize variables
                self.stop_loss_price = None
                self.close_qty = 0
                self.last_close_price = 0
                return_value=2 #If strategy resets, return 2 to reset candles
        return return_value  # if only trading parameters change, return false to keep candles

    def set_state(self,state: 'MartingaleStrategy'):
        self.strategy.last_known_price=state.strategy.last_known_price
        self.strategy.open_trades=state.strategy.open_trades
        if len(state.strategy.open_orders)>0:
            for index,order in enumerate(state.strategy.open_orders):
                if order.stop:
                    #order.name='SL'
                    self.stop_loss_price=order.price
                #else:
                #    order.name='Mart'+str(index+1)+'/'+str(self.martingale_number)
        self.strategy.open_orders=state.strategy.open_orders
        self.strategy.set_position()
        if self.strategy.position.qty is not None:
            self.close_qty = self.strategy.position.qty * self.tp_qty_percent  # Calculate TP qty
            self.close_qty = self.close_qty - self.close_qty % self.strategy.min_qty



