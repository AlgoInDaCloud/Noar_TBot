from flask import Flask
from config import Config
from flask_login import LoginManager
from flask_bootstrap import Bootstrap5

app = Flask(__name__)
app.config.from_object(Config)
login = LoginManager(app)
login.login_view = 'login'
bootstrap = Bootstrap5(app)


from app import routes