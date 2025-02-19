from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.fields.choices import SelectField
from wtforms.fields.datetime import DateTimeLocalField
from wtforms.fields.numeric import IntegerField, FloatField
from wtforms.validators import DataRequired, Regexp


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(),Regexp('\w{5,}',message="5 or more alphanumeric")])
    password = PasswordField('Password', validators=[DataRequired(),Regexp('(?=.*[A-Z])(?=.*[a-z])(?=.*[0-9])(?=.*[\?:,/]){8,}')])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')

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


