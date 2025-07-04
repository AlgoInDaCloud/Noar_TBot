import time
from typing import Literal
import ccxt
from app.files_rw import read_config_file
from app.logging import api_logger, trade_logger


class Api:
    def __init__(self,exchange_name:str):
        self.exchange_name=exchange_name
        self.exchange=self.connect_api(exchange_name)
        self.exchange.load_markets()
        self.retries=None

    def connect_api(self,api_name):
        try:
            exchange = None
            api_config=read_config_file("app/params/exchanges.ini")[api_name]
            exchange=getattr(ccxt, api_config['exchange'])
            exchange=exchange({
                        'headers':api_config['headers'],
                        'apiKey':api_config['api_key'],
                        'secret':api_config['api_secret'],
                        'password':api_config['api_pwd'],
                        'newUpdates': False
                    })
            #exchange.set_sandbox_mode(backtest)
            return exchange
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.connect_api(api_name)
            else:
                self.retries = None
                api_logger.exception(exception)



    def get_ohlc(self,symbol,timeframe,since=None,closed_candles=True,until=None,limit=None):
        try:
            history = list()
            if self.exchange.has['fetchOHLCV']:
                params={"until":int(until*1000)} if until is not None else {}
                raw_history=self.exchange.fetch_ohlcv(symbol, timeframe,int(since*1000) if until is None else None,limit=limit,params=params)

                if len(raw_history)>0:
                    keys = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume']
                    for row in raw_history:
                        row[0]=row[0]/1000
                        history.append(dict(zip(keys,row)))
                    if since is not None and history[0]['Time']<since: #Remove bars before what was asked
                        while True:
                            if history[0]['Time']<since:
                                history.pop(0)
                            else:
                                break
            return history
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.get_ohlc(symbol,timeframe,since,closed_candles,until,limit)
            else:
                self.retries = None
                api_logger.exception(exception)
            return list()

    def send_order(self,_symbol,_side,_qty,_type:Literal['limit','market']='limit',_price=None,_stop=False,_hedged=False,_isolated=True):
        try:
            trade_logger.info(("Trade" if _type=='market' else ("Stop" if _stop else "Limit"))
                              + "order"  + " : "+_symbol+ " " + _side.capitalize() + " " + str(_qty) +" @ "+ str(_price))
            param = {}
            match self.exchange_name.lower():
                case str(x) if "bitget" in x:
                    if _stop:
                        param['stopLossPrice'] = _price
                        param['holdSide'] = 'buy' if _side=='sell' else 'sell'
                        param['triggerType']='fill_price'
                        _price=None
                        if _qty is not None:
                            param['planType']='loss_plan'
                        _type='market'
                    if not _hedged:
                        param['oneWayMode'] = True
                    if _isolated:
                        param['marginMode'] = 'isolated'
            response=self.exchange.create_order(_symbol, _type, _side, _qty, price = _price, params = param)
            time.sleep(1)
            temp=self.get_order(response['id'], _symbol,_stop)
            return temp
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.send_order(_symbol,_side,_qty,_type,_price,_stop,_hedged,_isolated)
            else:
                self.retries = None
                api_logger.exception(exception)



    def get_order(self,_id,_symbol,_stop=False):
        try:
            match self.exchange_name.lower():
                case str(x) if "bitget" in x:
                    param={}
                    if _stop:
                        param['orderId']=_id
                        param['planType']='profit_loss'
                        raw=self.exchange.fetch_open_orders(symbol=_symbol, params=param)
                        if not len(raw)>0:
                            param['stop']=True
                            raw=self.exchange.fetch_closed_orders(symbol=_symbol, params=param)
                        if len(raw)>0:
                            response=raw[0]
                            response['price'] = response.pop('stopPrice')
                        else:
                            response=None
                    else:
                        response = self.exchange.fetch_order(_id, _symbol)
                        if response is not None:
                            if response['average'] is not None:
                                response['price'] = response.pop('average')
                    if response is not None:
                        if 'amount' in response: response['size']=response.pop('amount')
                        if 'side' in response: response['long']= True if response['side'] == 'buy' else False
                    return response
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.get_order(_id,_symbol,_stop)
            else:
                self.retries = None
                api_logger.exception(exception)


    def edit_order(self,_id,_symbol,_side,_size,_price,_type:Literal['limit','market']='limit',_stop=False,_hedged=False, _isolated=True):
        try:
            #api_logger.info(f"{self.get_order(_id,_symbol,_stop)}")
            trade_logger.info(f"Edit {'stop' if _stop else 'limit'} order : {_symbol} {_side.capitalize()} {str(_size)} @{str(_price)}")
            param = {}
            match self.exchange_name.lower():
                case str(x) if "bitget" in x:
                    if _stop:
                        param['stopLossPrice'] = _price
                        param['holdSide'] = 'buy' if _side=='sell' else 'sell'
                        _price=None
                        if _size is not None:
                            param['planType']='loss_plan'
                        _type='market'
                    if not _hedged:
                        param['oneWayMode'] = True
                    if _isolated:
                        param['marginMode'] = 'isolated'
            response=self.exchange.edit_order(_id, _symbol, _type, _side, _size, price=_price, params=param)
            time.sleep(1)
            return self.get_order(response['id'], _symbol,_stop)
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.edit_order(_id,_symbol,_side,_size,_price,_type,_stop,_hedged, _isolated)
            else:
                self.retries = None
                api_logger.exception(exception)

    def get_position(self,_symbol):
        try:
            response=self.exchange.fetch_position(_symbol)['info']
            match self.exchange_name.lower():
                case str(x) if "bitget" in x:
                    if not ('cTime' in response):return False
                    return {'open_time':int(response['cTime'])/1000,'open_price':float(response['openPriceAvg']),'long':True if response['holdSide']=='long' else False,'size':float(response['total']),'margin':float(response['marginSize']),'last_known_price':float(response['markPrice'])}
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.get_position(_symbol)
            else:
                self.retries = None
                api_logger.exception(exception)


    def get_open_orders(self,_symbol):
        if self.retries is None:self.retries=0
        try:
            if self.exchange.has['fetchOpenOrders']:
                response=self.exchange.fetch_open_orders(symbol=_symbol)
                response=response+ self.exchange.fetch_open_orders(symbol=_symbol, params={'planType':'profit_loss'})
                orders=[]
                for index, order in enumerate(response):
                    match self.exchange_name.lower():
                        case str(x) if "bitget" in x:
                            orders.append({'price':order['price'] if order['price'] is not None else order['stopPrice'],'long':True if order['side']=='buy' else False,'size':order['amount'],'name':'test','stop':True if order['stopLossPrice'] is not None else False,'id':order['id']})
                self.retries=None
                return orders
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.get_open_orders(_symbol)
            else:
                self.retries=None
                api_logger.exception(exception)

    def cancel_order(self,_id,_symbol):
        try:
            return self.exchange.cancel_order(_id, _symbol)
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.cancel_order(_id,_symbol)
            else:
                self.retries = None
                api_logger.exception(exception)
                return False

    def cancel_all_order(self,_symbol):
        try:
            return self.exchange.cancel_all_orders (symbol = _symbol)
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.cancel_all_order(_symbol)
            else:
                self.retries = None
                api_logger.exception(exception)

    def set_position_mode(self,_symbol=None,_hedged=False):
        try:
            self.exchange.set_position_mode(_hedged, symbol=_symbol)
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.set_position_mode(_symbol)
            else:
                self.retries = None
                api_logger.exception(exception)

    def set_margin_mode(self,_symbol=None,_cross=False):
        try :
            self.exchange.set_margin_mode('cross' if _cross else 'isolated', symbol=_symbol)
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.set_margin_mode(_symbol,_cross)
            else:
                self.retries = None
                api_logger.exception(exception)

    def set_leverage(self,_symbol=None,_leverage=1):
        try:
            self.exchange.set_leverage(_leverage, symbol=_symbol)
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.set_leverage(_symbol,_leverage)
            else:
                self.retries = None
                api_logger.exception(exception)

    def fetch_margin_rate(self,_symbol):
        try:
            return self.exchange.fetch_market_leverage_tiers(_symbol)[0]['maintenanceMarginRate']
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.fetch_margin_rate(_symbol)
            else:
                self.retries=None
                api_logger.exception(exception)

    def fetch_funding_rate(self,_symbol,_time):
        try:
            return self.exchange.fetch_funding_rate_history(_symbol,_time,1)[0]['fundingRate']
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.fetch_funding_rate(_symbol,_time)
            else:
                self.retries=None
                api_logger.exception(exception)

    def fetch_next_funding(self,_symbol,_time=None):
        try:
            if _time is None:
                return self.exchange.fetch_funding_interval(_symbol)['fundingTimestamp']/1000
            else:
                return self.exchange.fetch_funding_rate_history(_symbol,_time,1)[0]['timestamp']/1000
        except BaseException as exception:
            if self.retry_if_needed(exception):
                return self.fetch_next_funding(_symbol,_time)
            else:
                self.retries=None
                api_logger.exception(exception)

    def retry_if_needed(self,exception:BaseException):
        if isinstance(exception, ccxt.ExchangeNotAvailable):
            if self.retries < 3:
                self.retries += 1
                api_logger.exception(f"Request error, retry ({self.retries}) : {exception.__str__()}", exc_info=False)
                match self.retries:
                    case 1:
                        time.sleep(5*60) #first time, wait 5min
                    case 2:
                        time.sleep(3600) #seecond time, wait 1h
                    case 3:
                        time.sleep(3600*2) #third time, wait 2h
                return True
        return False
