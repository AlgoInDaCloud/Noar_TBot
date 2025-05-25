import importlib
import os.path
import threading
from configparser import ConfigParser
from operator import attrgetter

from app.files_rw import read_config_file, write_config_file, list_file_names, create_if_not_exists,CsvRW
from app.strategy import Bot, Optimizer
from app.threads import get_bots_threads, get_thread_by_name
from datetime import datetime
from flask import render_template, flash, redirect, url_for, request
from flask_login import current_user, login_user, logout_user, login_required
from urllib.parse import urlsplit
from app import app, forms
from app.forms import LoginForm
from app.models import User
from app.logging import routes_logger
from time import sleep

from config import BOTS_STATES


#Logging function
def login_function():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User()
        if form.username.data!=user.username or not user.check_password(form.password.data):
            flash('Invalid username or password')
            return redirect(url_for('login'))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or urlsplit(next_page).netloc != '':
            next_page = url_for('index')
        return redirect(next_page)
    return render_template('login.html', title='Sign In', form=form)

strategies={}
for strat in list_file_names('app/strategies'):
    running=[int(bot_id) for bot_id in (BOTS_STATES['RUNNING'][strat.lower()] if strat.lower() in BOTS_STATES['RUNNING'] else []) ]
    history=[int(bot_id) for bot_id in (BOTS_STATES['HISTORY'][strat.lower()] if strat.lower() in BOTS_STATES['HISTORY'] else []) ]
    strategies[strat]={'running':running,
           'history':history,
           'new_id':1+max(running+history,default=0)}
#Bot function
def bot_function(strategy_name=None,strategy_id=None,action=None):
    backtest_strategy = None
    candles = None
    #Get strategy parameters
    config_file=f"app/datas/strategies/{strategy_name}/{strategy_id}/parameters.ini"
    create_if_not_exists(config_file,f"app/params/{strategy_name}.ini")
    strat_param = read_config_file(config_file)['PARAMETERS']
    #Get available APIs
    available_apis=read_config_file('app/params/exchanges.ini').keys()
    #Get current thread if running
    current_thread=get_thread_by_name(strategy_name + '-bot' + strategy_id)
    #Get other running threads
    threads=get_bots_threads()

    module = importlib.import_module('app.strategies.' + strategy_name.capitalize())
    _class = getattr(module, strategy_name.capitalize()+'Parameter')
    form = _class(**strat_param)
    form.API.choices = [(api, api) for api in available_apis]

    if form.validate_on_submit():
        if form.submit.data:
            parameters=form.data
            remove_keys=['submit','start','stop','csrf_token']
            for key in remove_keys:parameters.pop(key,None)
            config = ConfigParser()
            config['PARAMETERS']=parameters
            write_config_file(config_file,{'PARAMETERS':parameters})
            if current_thread:
                current_thread.interrupt.set()
                sleep(1)
        elif form.start.data:
            #new_id = 1 if strategy_name not in threads['RUNNING']+threads['HISTORY'] else max((threads['RUNNING']+threads['HISTORY'])[strategy_name])+1
            bot_thread = Bot(name=strategy_name+'-bot'+str(strategy_id))
            bot_thread.set_strategy(strategy_name.capitalize(),strat_param,False)
            bot_thread.start()
        elif form.stop.data:
            if current_thread:
                current_thread.stop()
                current_thread.interrupt.set()
                sleep(1)
        return redirect('/' + strategy_name + '/' + strategy_id)
    form.API.data = strat_param['api']

    if action=="backtest":
        bot_thread = Bot(name=strategy_name+'-bot'+str(strategy_id))
        bot_thread.set_strategy(strategy_name.capitalize(),strat_param)
        backtest_strategy,candles = bot_thread.backtest()
    
    if current_thread:
        backtest_strategy=current_thread.strategy.strategy
        candles=current_thread.candles

    if candles is not None and len(candles.history)>50:
        page = request.args.get('page')
        if page is not None:
            page=int(page)
            #candles.history=candles.history[50*page:49*(page+1)]

    return render_template('strategy.html', title=strategy_name.capitalize()+'-bot', form=form,
                                   thread=current_thread, threads=sorted(threads,key=attrgetter('name')), backtest_strategy=backtest_strategy,
                                   candles=candles,strategy_name=strategy_name,action=action,strategies=strategies)

#Optimize function
from io import BytesIO
import base64
import matplotlib.pyplot as plt
def optimize_function(strategy_name=None):
    # Get optimizer parameters
    config_file = f"app/datas/strategies/{strategy_name}/optimizer/parameters.ini"
    create_if_not_exists(config_file,f"app/params/{strategy_name}-optimizer.ini")
    strat_param = read_config_file(config_file)['PARAMETERS']
    # Get available APIs
    available_apis = read_config_file('app/params/exchanges.ini').keys()
    # Get current thread if running
    current_thread = get_thread_by_name(strategy_name + '-optimizer')
    # Get other running threads
    threads = get_bots_threads()
    for thread in threading.enumerate():
        print(thread.name)

    #Log file path
    log_file='app/datas/strategies/martingale/optimizer/'+strat_param['symbol']+'_'+strat_param['timeframe']+'_'+strat_param['start_date'].strftime('%Y-%m-%d %H:%M:%S')+'.log'


    module = importlib.import_module('app.strategies.' + strategy_name.capitalize())
    _class = getattr(module, strategy_name.capitalize() + 'OptimizerParameter')
    form = _class(**strat_param)
    form.API.choices = [(api, api) for api in available_apis]

    if form.validate_on_submit():
        if form.submit.data:
            parameters=form.data
            remove_keys=['submit','start','stop','csrf_token']
            for key in remove_keys:parameters.pop(key,None)
            config = ConfigParser()
            config['PARAMETERS']=parameters
            write_config_file(config_file,{'PARAMETERS':parameters})
            if current_thread:
                current_thread.interrupt.set()
                sleep(1)
        elif form.start.data:
            #new_id = 1 if strategy_name not in threads['RUNNING']+threads['HISTORY'] else max((threads['RUNNING']+threads['HISTORY'])[strategy_name])+1
            bot_thread = Optimizer(name=strategy_name+'-optimizer',parameters=strat_param)
            create_if_not_exists(log_file)
            bot_thread.start()
        elif form.stop.data:
            if current_thread:
                current_thread.stop()
                current_thread.interrupt.set()
                sleep(1)
        return redirect('/' + strategy_name + '/optimize')
    form.API.data = strat_param['api']

    backtests=list(dict())
    plot_url=""
    if current_thread:
        backtests=current_thread.backtests
        backtests.sort(key=lambda k: k['pnl'], reverse=True)
        img = BytesIO()
        plt.plot(range(0,len(current_thread.loss_function)),current_thread.loss_function)
        plt.savefig(img, format='png')
        plt.close()
        img.seek(0)
        plot_url = base64.b64encode(img.getvalue())
        plot_url = plot_url.decode()
    elif os.path.exists(log_file):
        reader = CsvRW(log_file)
        reader.read_normal()
        for csv_line in reader.readline:
            backtests.append(csv_line)
        backtests.sort(key=lambda k:k['pnl'],reverse=True)

    return render_template('optimizer.html',title=strategy_name.capitalize()+'-optimizer', form=form,
                                   thread=current_thread, threads=sorted(threads,key=attrgetter('name')), backtests=backtests,
                                   strategy_name=strategy_name,action='optimize',strategies=strategies,plot=plot_url)


@app.route('/')
@app.route('/index')
@login_required
def index():
    try:
        return render_template('index.html', title='Home', threads=get_bots_threads(), strategies=strategies)
    except BaseException as exception:
        routes_logger.exception(exception)
        return render_template('error.html',title="Error during execution")

@app.route('/<strategy_name>/<strategy_id>', methods=['GET', 'POST'])
@app.route('/<strategy_name>/<strategy_id>/<action>/', methods=['GET', 'POST'])
@login_required
def bot(strategy_name=None,strategy_id=None,action=None):
    try:
        if strategy_id=='optimize':
            return optimize_function(strategy_name)
        else:
            return bot_function(strategy_name,strategy_id,action)
    except BaseException as exception:
        routes_logger.exception(exception)
        return render_template('error.html',title="Error during execution")


@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        return login_function()
    except BaseException as exception:
        routes_logger.exception(exception)
        return render_template('error.html',title="Error during execution")


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.template_filter('format_timestamp')
def format_timestamp(timestamp,format='%d-%m-%Y %H:%M:%S'):
    return datetime.fromtimestamp(timestamp).strftime(format) # datetime.datetime.fromtimestamp(s)

'''
import app.wip.AssetManager
def asset_manager(strategy_name,action):
    bot_thread = Bot()
    bot_thread.strategy=app.wip.AssetManager.AssetManagerStrategy({'api':'BITGET_REAL','timeframe':'1D'},False)
    bot_thread.name = "AssetManager-bot"
    markets=bot_thread.strategy.api.exchange.markets
    return render_template('wip/asset_manager.html',title=bot_thread.name,markets=markets)
'''
