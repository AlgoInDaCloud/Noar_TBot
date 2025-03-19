from app.files_rw import read_config_file
class Config:
    vars=read_config_file('.env_var.ini')['ENV_VARS']
    SECRET_KEY = vars['secret_key']
    PWD_KEY = vars['pwd_key']

BOTS_STATES = read_config_file('app/params/bots.ini')