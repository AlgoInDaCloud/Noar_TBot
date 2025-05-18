from datetime import datetime
from app.api import Api
from app.files_rw import config_update
from app.logging import trade_logger
from app.models import Strategy, Candles
import copy

from flask_wtf import FlaskForm
from wtforms.fields.choices import SelectField
from wtforms.fields.datetime import DateTimeLocalField
from wtforms.fields.numeric import IntegerField, FloatField
from wtforms.validators import DataRequired, InputRequired
from wtforms import SubmitField
class MartingaleParameter(FlaskForm):
    API = SelectField('API',choices=[('bitget', 'Bitget')],validators=[DataRequired()])
    symbol=SelectField("Symbol", choices=[('BTC/USDT:USDT','BTCUSDT Futures')],validators=[DataRequired()])
    timeframe=SelectField('Timeframe', choices=[('1m','1m'),('5m','5m'),('15m','15m'),('30m','30m'),('1h','1h'),('4h','4h'),('1d','1d')],validators=[DataRequired()])
    martingale_number=IntegerField('Martingale number',[DataRequired()])
    leverage=IntegerField('Leverage',[DataRequired()])
    pivot_width=IntegerField('Pivot width',[DataRequired()])
    tp_qty_percent=IntegerField('TP % of trade',[DataRequired()])
    profit_sl_activation=FloatField('%Profit for SL activation',[DataRequired()])
    dist_btw_tp=FloatField('%distance between TP',[DataRequired()])
    initial_capital=IntegerField('Initial capital',[DataRequired()])
    start_date=DateTimeLocalField('Start date',validators=[DataRequired()])
    rsi_length=IntegerField('RSI length',[DataRequired()],default=14)
    rsi_ob = IntegerField('RSI overbought', [DataRequired()], default=70)
    rsi_os = IntegerField('RSI oversold', [DataRequired()], default=30)
    submit = SubmitField('Save')
    start = SubmitField('Start')
    stop = SubmitField('Stop')

class MartingaleOptimizerParameter(FlaskForm):
    API = SelectField('API',choices=[('bitget', 'Bitget')],validators=[DataRequired()])
    symbol=SelectField("Symbol", choices=[('BTC/USDT:USDT','BTCUSDT Futures')],validators=[DataRequired()])
    timeframe=SelectField('Timeframe', choices=[('1m','1m'),('5m','5m'),('15m','15m'),('30m','30m'),('1h','1h'),('4h','4h'),('1d','1d')],validators=[DataRequired()])
    martingale_number_min=IntegerField('Min Martingale number',[DataRequired()])
    martingale_number_max = IntegerField('Max Martingale number', [DataRequired()])
    leverage_min=IntegerField('Leverage min',[DataRequired()])
    leverage_max = IntegerField('Leverage max', [DataRequired()])
    pivot_width_min=IntegerField('Pivot width min',[DataRequired()])
    pivot_width_max = IntegerField('Pivot width max', [DataRequired()])
    tp_qty_percent_min=IntegerField('TP % of trade min',[DataRequired()])
    tp_qty_percent_max = IntegerField('TP % of trade max', [DataRequired()])
    profit_sl_activation_min=FloatField('%Profit for SL activation min',[InputRequired()])
    profit_sl_activation_max = FloatField('%Profit for SL activation max', [DataRequired()])
    dist_btw_tp_min=FloatField('%distance between TP min',[DataRequired()])
    dist_btw_tp_max = FloatField('%distance between TP max', [DataRequired()])
    initial_capital=IntegerField('Initial capital',[DataRequired()])
    start_date=DateTimeLocalField('Start date',validators=[DataRequired()])
    rsi_length_min=IntegerField('RSI length min',[DataRequired()],default=14)
    rsi_length_max = IntegerField('RSI length max', [DataRequired()], default=14)
    rsi_ob = IntegerField('RSI overbought', [DataRequired()], default=70)
    rsi_os_min = IntegerField('RSI oversold min', [DataRequired()], default=30)
    rsi_os_max = IntegerField('RSI oversold max', [DataRequired()], default=30)
    submit = SubmitField('Save')
    start = SubmitField('Start')
    stop = SubmitField('Stop')

class MartingaleStrategy:
    def __init__(self,parameters,_backtest=False):
        self.name= 'martingale'
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
        self.security=0.005 # security taken between mart order and liquidation (percent)

        #Set objects
        self.api=Api(self.platform_api)
        self.strategy=Strategy(None,self.initial_capital,self.leverage,start_date=self.start_date,api=self.api,symbol=self.symbol)
        self.init_order=self.strategy.Order(_size=0,_price=None,_long=True,_type='market',_stop=False,_name='Entry')
        self.tp_order=self.strategy.Order(_size=0,_price=None,_long=False,_type='market',_stop=False,_name='TP')
        self.sl_order=self.strategy.Order(_size=0,_price=None,_long=False,_type='market',_stop=True,_name='SL')
        #Initialize variables
        self.stop_loss_price = None
        self.close_qty=0
        self.last_close_price = 0


    def apply_strategy(self,candles:Candles,current_index=0):
        #self.update_filled_orders(candles.history[current_index])
        self.strategy.last_known_price = candles.history[current_index]['Close']
        self.strategy.set_fundings(candles.history[current_index]['Time'],candles.history[current_index]['Close'])
        self.strategy.set_runup_drawdown(candles.history[current_index])
        if self.strategy.position is None:
            if self.trade_condition(candles.history[current_index],candles.history[current_index+1]):
                amount_per_order = round(self.strategy.get_equity() * self.strategy.leverage / (self.martingale_number + 1),10)  # Funds available per order
                self.init_order.price = candles.history[current_index]['Close']
                self.init_order.size = round(self.strategy.min_qty * int(round((amount_per_order / self.init_order.price) / self.strategy.min_qty,10)),10) # size => round to min qty
                self.init_order.long=True
                if self.init_order.size > 0:  # If enough, set trade, martingale orders and liquidation price
                    self.init_order.time=candles.history[current_index]['Time']
                    candles.history[current_index]['Trade'] = "Entry"
                    self.launch_martingale(amount_per_order)
                    self.tp_order.size = round(self.strategy.min_qty * int(round((self.strategy.open_trades[-1].qty * self.tp_qty_percent) / self.strategy.min_qty,10)),10) # Calculate TP qty
                else:
                    trade_logger.warning("Error:Not enough capital for trading")
        else:  # If in trade, check if TP, martingales ou SL orders have been triggered, and update runups/drawdowns
            if self.sl_order.price is None or self.sl_order.price == 0:  # if still in martingale phase
                if self.sl_order.price is None and candles.history[current_index]['Close'] > self.strategy.position.open_price * (1 + self.profit_sl_activation):
                    trade_logger.info('SL activation')
                    self.sl_order.price = 0  # activate SL calculation if price rise above parameter
                if self.sl_order.price == 0 \
                    and candles.history[current_index]['PivotsHL']['low'] is not None \
                    and candles.history[current_index]['PivotsHL']['low'] > self.strategy.position.open_price:  # If pivot in profit, activate SL and deactivate the rest
                    self.strategy.cancel_orders(backtest=self.backtest)
                    self.sl_order.price=candles.history[current_index]['PivotsHL']['low']
                    self.sl_order.size=self.strategy.position.qty
                    self.sl_order.long=not self.strategy.position.long
                    self.sl_order.time=int(candles.history[current_index]['Time'])
                    self.strategy.open_order(self.sl_order,self.backtest)
            if self.close_qty>0 \
                and self.tp_condition(candles.history[current_index], candles.history[current_index + 1]):  # Check for signal and if enough funds for tp
                    self.tp_order.price=candles.history[current_index]['Close']
                    self.tp_order.long=not self.strategy.position.long
                    self.tp_order.time=int(candles.history[current_index]['Time'])
                    self.strategy.close_order(self.tp_order,self.backtest)
                    print(datetime.fromtimestamp(candles.history[current_index]['Time']),' TP', self.tp_order.price)
                    candles.history[current_index]['Trade'] = "TP"
                    trade=self.strategy.closed_trades[-1]
                    trade_logger.info(f"TP : {datetime.fromtimestamp(int(candles.history[current_index]['Time']))} Sell {trade.qty} @{trade.close_price} /{self.close_qty},{candles.history[current_index]['Close']}")
                    self.last_close_price=candles.history[current_index]['Close']
                    if self.strategy.position is None:
                        self.strategy.open_orders=[]
                        self.tp_order.price=0
                        self.tp_order.size=0
                        self.sl_order.price=None

            if self.strategy.position is not None and candles.history[current_index]['Low'] < self.strategy.position.get_liquidation_price():  # if liquidated...sorry dude
                trade_logger.info('Liquidation')
                order=self.strategy.Order(self.strategy.position.qty,self.strategy.position.get_liquidation_price(),not self.strategy.position.long,'market',False,'Liquidation',candles.history[current_index]['Time'])
                self.strategy.close_order(order,True) # Only log the transaction
                self.tp_order.price = 0  # reset variables
                self.sl_order.price = None
            if (self.sl_order.price is not None and self.sl_order.price > 0
                    and candles.history[current_index]['PivotsHL']['low'] is not None and candles.history[current_index]['PivotsHL']['low']>self.sl_order.price):
                trade_logger.info('Editing SL')
                self.sl_order.price = candles.history[current_index]['PivotsHL']['low']
                self.strategy.edit_order(self.sl_order,self.backtest)
        return

    def launch_martingale(self, _amount_per_order):
        temp_strategy = Strategy(leverage=self.strategy.leverage,
                                 taker_fee=self.strategy.taker_fee)
        temp_strategy.min_qty=self.strategy.min_qty
        self.strategy.open_order(self.init_order,self.backtest)
        temp_strategy.open_order(self.init_order,True)
        for i in range(self.martingale_number):
            mart_price=round(temp_strategy.position.get_liquidation_price() * (1 + self.security),10)
            order=self.strategy.Order(
                    _size=round(_amount_per_order / mart_price,10),
                    _price=mart_price,
                    _long=self.init_order.long,
                    _type='limit',
                    _stop=False,
                    _name="Mart" + str(i+1) + "/" + str(self.martingale_number)
                 )          
            order=self.strategy.open_order(order,self.backtest)
            trade=copy.deepcopy(order)
            trade.type='market'
            temp_strategy.open_order(trade,True)
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
                    self.sl_order.price=order.price
                    self.sl_order.size=order.size
                    self.sl_order.id=order.id
                #else:
                #    order.name='Mart'+str(index+1)+'/'+str(self.martingale_number)
        self.strategy.open_orders=state.strategy.open_orders
        self.strategy.set_position()
        if self.strategy.position.qty is not None:
            self.tp_order.size = round(self.strategy.min_qty * int(round((self.strategy.position.qty * self.tp_qty_percent) / self.strategy.min_qty,10)),10) # Recalculate TP qty

    def update_filled_orders(self, candle):
        orders_filled = self.strategy.check_orders(candle,self.backtest)
        if len(orders_filled)>0:
            if 'SL' in orders_filled:
                self.tp_order.price = 0
                self.sl_order.price = None
                self.strategy.liquidation_price = None
            candle['Trade'] = f"Filled : {orders_filled}"


