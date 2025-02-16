import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    PWD_KEY = os.environ.get('PWD_KEY')
