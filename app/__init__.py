import threading

from flask import Flask

from app.files_rw import restore_state
from config import Config, BOTS_STATES
from flask_login import LoginManager
from flask_bootstrap import Bootstrap5

app = Flask(__name__)
app.config.from_object(Config)
login = LoginManager(app)
login.login_view = 'login'
bootstrap = Bootstrap5(app)

#Restore running threads in case of server restart
from app.strategy import Bot
for strategy_name,ids in BOTS_STATES['RUNNING'].items():
    for id in ids:
        bot_thread = restore_state(f"app/datas/strategies/{strategy_name}/{id}/state")
        if bot_thread:
            bot_thread.start()

from app import routes