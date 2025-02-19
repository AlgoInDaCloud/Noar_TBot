import logging


def setup_logger(name, log_file, level=logging.INFO):
    """To setup as many loggers as you want"""
    handler = logging.FileHandler(log_file)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger

app_logger=setup_logger('app_logger','app/logs/app.log')
routes_logger=setup_logger('routes_logger','app/logs/routes.log')
strategy_logger=setup_logger('strategy_logger','app/logs/strategy.log')
api_logger=setup_logger('api_logger','app/logs/api.log')

trade_logger=setup_logger('trade_logger','app/logs/trades.log')