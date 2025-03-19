#flaskapp.wsgi
import sys
import os
sys.path.insert(0, '/var/www/noar-tbot.ip-ddns.com/Noar_TBot')
os.chdir(os.path.dirname(__file__))
from app import app as application

