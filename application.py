from flask import Flask, redirect, url_for, request, render_template, abort, flash, get_flashed_messages, session, g
from flaskext.oauth import OAuth
app = Flask(__name__)

from google.appengine.ext import db
from google.appengine.api import users, taskqueue
import logging

import conf
from models import *


app.debug = True
logging.getLogger().setLevel(logging.DEBUG)

def TwitterOAuth():
    return OAuth().remote_app('twitter',
                              base_url='http://api.twitter.com/1/',
                              request_token_url='http://api.twitter.com/oauth/request_token',
                              access_token_url='http://api.twitter.com/oauth/access_token',
                              authorize_url='http://api.twitter.com/oauth/authenticate',
                              consumer_key=conf.consumer_key,
                              consumer_secret=conf.consumer_secret
                              )

twitter = TwitterOAuth()
selftwitter = TwitterOAuth()

def login_required(path):
    actions = [
        "/dashboard",
        "/deactivate"
               ]
    for action in actions:
        if action == path:
            return True
    return False

@app.before_request
def before_request():
    g.user = None
    if 'user_key' in session:
        g.user = db.get(session['user_key'])
    if login_required(request.path):
        if not g.user: return redirect('/')

@twitter.tokengetter
def get_twitter_token():
    user = g.user
    if user is not None:
        return user.oauth_token, user.oauth_secret
    return None

@app.route('/')
def index():
    if g.user is not None:
        return redirect('/dashboard')

    return render_template('index.html')

@app.route('/login')
def login():
    return twitter.authorize(callback=url_for('oauth_authorized',
                                              next=request.args.get('next') or request.referrer or None))

@app.route('/dashboard')
def dashboard():
    resp = twitter.get('users/show.json?screen_name=' + g.user.name)

    user_icon = None
    if resp.status == 200:
        user_icon = resp.data['profile_image_url']

    tweets=[]
    if g.user.target_screen_name:
        tweets = Tweet.find_by_1day_schedule(base_screen_name=g.user.name, screen_name=g.user.target_screen_name, span=g.user.turn_around_span_days)
    return render_template('show_user.html', user_icon_url=user_icon, tweets=tweets)

@app.route('/oauth-authorized')
@twitter.authorized_handler
def oauth_authorized(resp):
    next_url = request.args.get('next') or url_for('index')

    if resp is None:
        flash(u'You denied the request to sign in.')
        return redirect(next_url)

    user = User.get(resp['screen_name'])

    if user is None:
        user = User(twitter_id = int(resp['user_id']),
                    name = resp['screen_name'],
                    oauth_token = resp['oauth_token'],
                    oauth_secret = resp['oauth_token_secret']
                    )
        db.put(user)

    session['user_key'] = user.key()
    flash('You were signed in')
    return redirect(next_url)

@app.route('/update', methods=['POST'])
def update():
    target_screen_name = request.form['target_screen_name']
    current = db.get(session['user_key'])
    current.target_screen_name = target_screen_name
    current.turn_around_span_days = int(request.form['turn_around_span_days'])
    db.put(current)

    taskqueue.add(url='/task/user_initialize/' + current.name, method='GET')

    return render_template('update.html', target=request.form['target_screen_name'])

@app.route('/deactivate')
def deactivate():
    user = db.get(session['user_key'])
    while True:
        tweets = []
        tweets = db.Query(Tweet).filter('base_screen_name = ', user.name).fetch(1000)
        if len(tweets) == 0:
            break

        for tweet in tweets:
            db.delete(tweet)
    user.delete()
    return redirect('/')

@app.route('/logout')
def logout():
    session.pop('user_key', None)
    flash('You where signed out')
    return redirect('/')


# set the secret key.  keep this really secret:
app.secret_key = 'the secret key'

if __name__ == '__main__':
    from wsgiref.handlers import CGIHandler
    CGIHandler().run(app)
