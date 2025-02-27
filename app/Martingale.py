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

        #Set objects
        self.api=Api(self.platform_api)
        self.strategy=Strategy(None,self.initial_capital,self.leverage,start_date=self.start_date,api=self.api,symbol=self.symbol)

        #Set backtest or trade functions
        self.trade_function = self.strategy.open_trade
        self.order_function = self.strategy.open_order
        self.cancel_order_function = self.strategy.cancel_orders
        self.close_order_function = self.strategy.close_order
        self.edit_order_function = self.strategy.edit_order
        if _backtest:
            self.trade_function=self.strategy.log_trade
            self.order_function=self.strategy.log_order
            self.cancel_order_function = self.strategy.remove_log_orders
            self.close_order_function = self.strategy.log_close_order
            self.edit_order_function = self.strategy.edit_log_order

        #Initialize variables
        self.stop_loss = None
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
                print('quntité',qty,'Amount=',amount_per_order)
                #print(datetime.fromtimestamp(candles.history[current_index]['Time']),self.strategy.get_equity(),qty)
                if qty > 0:  # If enough, set trade, martingale orders and liquidation price
                    candles.history[current_index]['Trade'] = "Entry"
                    self.launch_martingale(candles.history[current_index]['Time'], candles.history[current_index]['Close'], True,
                                      amount_per_order, qty)
                    self.close_qty = self.strategy.open_trades[-1].qty * self.tp_qty_percent  # Calculate TP qty
                    self.close_qty = self.close_qty - self.close_qty % self.strategy.min_qty
                else:
                    trade_logger.warning("Error:Not enough capital for trading")
        else:  # If in trade, check if TP, martingales ou SL orders have been triggered, and update runups/drawdowns
            #trade_logger.info('in trade')
            #trade_logger.info('SL=' + str(self.stop_loss)
            #               + " PivotL=" + str(candles.history[current_index]['PivotsHL']['low'])
            #               + " AvgPrice=" + str(self.strategy.position.open_price)
            #               + " ClosePrice=" + str(candles.history[current_index]['Close'])
            #               + " SLActPrice=" + str(self.strategy.position.open_price * (1 + self.profit_sl_activation)))
            if self.stop_loss is None or self.stop_loss == 0:  # if still in martingale phase
                #trade_logger.info('still mart')
                if self.stop_loss is None and candles.history[current_index]['Close'] > self.strategy.position.open_price * (
                        1 + self.profit_sl_activation):
                    trade_logger.info('SL activation')
                    self.stop_loss = 0  # activate SL calculation if price rise above parameter

                if self.stop_loss == 0 and candles.history[current_index]['PivotsHL']['low'] is not None and candles.history[current_index]['PivotsHL']['low'] > self.strategy.position.open_price:  # If pivot in profit, activate SL and deactivate the rest
                    self.cancel_order_function()
                    self.stop_loss = candles.history[current_index]['PivotsHL']['low']
                    self.order_function(self.stop_loss, False,self.strategy.position.qty,'SL',True)
                    trade_logger.info(f'SL : {datetime.fromtimestamp(candles.history[current_index]['Time'])} Sell {self.strategy.position.qty} @ {self.stop_loss}')

            if self.close_qty>0 and self.tp_condition(candles.history[current_index], candles.history[current_index + 1]):  # Check for signal and if enough funds for tp
                    self.close_order_function(int(candles.history[current_index]['Time']),
                                             self.close_qty, "TP", candles.history[current_index]['Close'])
                    candles.history[current_index]['Trade'] = "TP"
                    trade=self.strategy.closed_trades[-1]
                    trade_logger.info(f'TP : {datetime.fromtimestamp(int(candles.history[current_index]['Time']))} Sell {trade.qty} @{trade.close_price} /{self.close_qty},{candles.history[current_index]['Close']}')
                    self.last_close_price=candles.history[current_index]['Close']

            orders_filled = self.strategy.check_orders(candles.history[current_index])
            for order in orders_filled:
                trade_logger.info(f'{order.name} order filled : {datetime.fromtimestamp(candles.history[current_index]['Time'])} {'Buy' if order.long else 'Sell'} {order.qty} @{order.limit}')
                if order.stop:
                    self.close_order_function(candles.history[current_index]['Time'], order.qty, "SL", order.limit)
                    candles.history[current_index]['Trade'] = "SL"
                    #self.cancel_order_function()
                    self.last_close_price = 0
                    self.stop_loss = None
                    self.strategy.liquidation_price=None
                elif order.limit is not None:
                    self.trade_function(candles.history[current_index]['Time'],order.limit, True, order.qty, order.name)
                    candles.history[current_index]['Trade'] = "Mart"

            if self.strategy.position is not None and candles.history[current_index]['Low'] < self.strategy.position.get_liquidation_price():  # if liquidated...sorry dude
                trade_logger.info('Liquidation')

                self.strategy.log_close_order(candles.history[current_index]['Time'],
                                         self.strategy.position.qty, "Liquidation", self.strategy.position.get_liquidation_price())
                self.last_close_price = 0  # reset variables
                self.stop_loss = None
            if (self.stop_loss is not None and self.stop_loss > 0
                    and candles.history[current_index]['PivotsHL']['low'] is not None and candles.history[current_index]['PivotsHL']['low']>self.stop_loss):
                trade_logger.info('Editing SL')
                self.edit_order_function(self.strategy.open_orders[0].id,candles.history[current_index]['PivotsHL']['low'],self.strategy.open_orders[0].long,self.strategy.open_orders[0].qty,True,self.symbol)
        return

    def launch_martingale(self, time, _initial_price, _long, _amount_per_order, _initial_qty, _security=0.005):
        temp_strategy = Strategy(leverage=self.strategy.leverage,
                                 taker_fee=self.strategy.taker_fee)
        self.trade_function(time, _initial_price, _long, _initial_qty, 'Entry')
        # strategy.open_trade(time,_initial_price,_long,_initial_qty,'Entry')
        temp_strategy.log_trade(time, _initial_price, _long, _initial_qty)
        trade=self.strategy.open_trades[-1]
        trade_logger.info(f'Entry : {datetime.fromtimestamp(trade.open_time)} {'buy'if trade.long else 'sell'} {trade.qty} @{trade.open_price}')
        for i in range(self.martingale_number):
            mart_price = temp_strategy.position.get_liquidation_price() * (1 + _security)
            mart_qty = round(_amount_per_order / mart_price, 4)
            self.order_function(mart_price, _long, mart_qty,"Mart" + str(i) + "/" + str(self.martingale_number),False)
            temp_strategy.log_trade(time, mart_price, _long, mart_qty)
            trade_logger.info(f'Mart{i} : {datetime.fromtimestamp(time)} {'buy' if _long else 'sell'} {mart_qty} @{mart_price}')
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
                self.stop_loss = None
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
                    order.name='SL'
                else:
                    order.name='Mart'+str(index+1)+'/'+str(self.martingale_number)
        self.strategy.open_orders=state.strategy.open_orders
        self.strategy.set_position()


