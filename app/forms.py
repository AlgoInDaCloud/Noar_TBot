from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Regexp

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(),Regexp(r'\w{5,}',message="5 or more alphanumeric")])
    password = PasswordField('Password', validators=[DataRequired(),Regexp(r'(?=.*[A-Z])(?=.*[a-z])(?=.*[0-9])(?=.*[\?:,/]){8,}')])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')