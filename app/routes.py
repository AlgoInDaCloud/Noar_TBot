import threading
from configparser import ConfigParser
from app.files_rw import read_config_file
from app.strategy import Bot
from app.threads import get_bots_threads, get_thread_by_name
from datetime import datetime
from flask import render_template, flash, redirect, url_for, request
from flask_login import current_user, login_user, logout_user, login_required
from urllib.parse import urlsplit
from app import app, forms
from app.forms import LoginForm
from app.models import User
from app.logging import routes_logger


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

#Bot function
def bot_function(strategy_name=None,action=None):
    backtest_strategy = None
    candles = None
    #Get strategy parameters
    config_file='app/params/'+strategy_name+'.ini'
    strat_param = read_config_file(config_file)['PARAMETERS']
    #Get available APIs
    available_apis=read_config_file('app/params/exchanges.ini').keys()

    #module = importlib.import_module('app.' + strategy_name.capitalize())
    _class = getattr(forms, strategy_name.capitalize()+'Parameter')
    form = _class(**strat_param)
    form.API.choices = [(api, api) for api in available_apis]

    if form.validate_on_submit():
        if form.submit.data:
            parameters=form.data
            remove_keys=['submit','start','stop','csrf_token']
            for key in remove_keys:parameters.pop(key,None)
            config = ConfigParser()
            config['PARAMETERS']=parameters
            print(parameters)
            with open(config_file, 'w') as configfile:  # save
                config.write(configfile)
        elif form.start.data:
            bot_thread = Bot()
            bot_thread.set_strategy(strategy_name.capitalize(),strat_param,False)
            bot_thread.name = strategy_name.capitalize()+'-bot'
            bot_thread.start()
        elif form.stop.data:
            for thread in threading.enumerate():
                if thread.name == strategy_name.capitalize()+'-bot':
                    thread.stop()
                    thread.interrupt.set()
        return redirect('/' + strategy_name)
    form.API.data = strat_param['api']

    if action=="backtest":
        bot_thread = Bot()
        bot_thread.set_strategy(strategy_name.capitalize(),strat_param)
        bot_thread.name = strategy_name.capitalize()+'-bot'
        backtest_strategy,candles = bot_thread.backtest()
        #candles.history=candles.history[0:50]
    if action=='maman':
        print('maman')
        #test_orders()

    for thread in threading.enumerate():
        if thread.name == strategy_name.capitalize()+'-bot':
            backtest_strategy=thread.strategy.strategy
            candles=thread.candles

    if candles is not None and len(candles.history)>50:
        page = request.args.get('page')
        if page is not None:
            page=int(page)
            #candles.history=candles.history[50*page:49*(page+1)]
    return render_template('strategy.html', title=strategy_name.capitalize()+'-bot', form=form,
                                   thread=get_thread_by_name(strategy_name.capitalize()+'-bot'), backtest_strategy=backtest_strategy,
                                   candles=candles,strategy_name=strategy_name,action=action)

@app.route('/')
@app.route('/index')
@login_required
def index():
    try:
        return render_template('index.html', title='Home', threads=get_bots_threads())
    except BaseException as exception:
        routes_logger.exception(exception)
        return render_template('error.html',title="Error during execution")

@app.route('/<strategy_name>/', methods=['GET', 'POST'])
@app.route('/<strategy_name>/<action>/', methods=['GET', 'POST'])
@login_required
def bot(strategy_name=None,action=None):
    try:
        return bot_function(strategy_name,action)
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