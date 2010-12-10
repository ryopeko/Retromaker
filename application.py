from flask import Flask, redirect, url_for, request, render_template, abort, flash, get_flashed_messages, session, g
from flaskext.oauth import OAuth
app = Flask(__name__)

from google.appengine.ext import db
from google.appengine.api import users, memcache, taskqueue
import logging
import datetime
import time
import re
import hashlib

import conf
from models import *


app.debug = True
logging.getLogger().setLevel(logging.DEBUG)

oauth = OAuth()
twitter = oauth.remote_app('twitter',
                           base_url='http://api.twitter.com/1/',
                           request_token_url='http://api.twitter.com/oauth/request_token',
                           access_token_url='http://api.twitter.com/oauth/access_token',
                           authorize_url='http://api.twitter.com/oauth/authenticate',
                           consumer_key=conf.consumer_key,
                           consumer_secret=conf.consumer_secret
)

selfoauth = OAuth()
selftwitter = selfoauth.remote_app('twitter',
                                   base_url='http://api.twitter.com/1/',
                                   request_token_url='http://api.twitter.com/oauth/request_token',
                                   access_token_url='http://api.twitter.com/oauth/access_token',
                                   authorize_url='http://api.twitter.com/oauth/authenticate',
                                   consumer_key=conf.consumer_key,
                                   consumer_secret=conf.consumer_secret
                                   )

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

@selftwitter.tokengetter
def selftoken():
    return conf.oauth_token, conf.oauth_secret

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

    user = User.get(resp['user_id'])

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
    logging.debug(request.form['target_screen_name'])
    target_screen_name = request.form['target_screen_name']
    current = db.get(session['user_key'])
    current.target_screen_name = target_screen_name
    current.turn_around_span_days = int(request.form['turn_around_span_days'])
    db.put(current)

    now = datetime.datetime.utcnow()
    now = datetime.datetime(now.year, now.month, now.day, now.hour, now.minute)

    depth = 0
    tweets = []

    taskqueue.add(url='/user_initialize/' + current.name, method='GET')

    return render_template('update.html', target=request.form['target_screen_name'], tweets=tweets)

@app.route('/user_timeline',methods=['POST'])
def user_timeline():
    target_screen_name = request.form['target_screen_name']
    daynum = int(request.form['daynum'])
    now = drop_seconds(datetime.datetime.utcnow())

    depth = 0
    tweets=[]
    if g.user is not None:
        while depth < 4:
            depth += 1

            url = 'statuses/user_timeline.json?count=200&screen_name=' + target_screen_name
            url += '&page=' + str(depth) if depth > 1 else ""

            resp = twitter.get(url)

            if resp.status == 200 and len(resp.data) > 0:
               extract_tweets = get_target_tweets(resp, now, daynum)
               if len(extract_tweets) == 0: break

               tweets += extract_tweets
            else:
                logging.debug('Unable to load tweets from Twitter. Maybe out of '
                              'API calls or Twitter is overloaded.')
                break
    return render_template('user_timeline.html', tweets=tweets)

@app.route('/tweet')
def tweet():
    users = db.Query(User).fetch(1000)

    for user in users:
        g.user = user
        target_screen_name = user.target_screen_name
        now = drop_seconds(datetime.datetime.utcnow()) - datetime.timedelta(g.user.turn_around_span_days)
        tweets = Tweet.get_by_datetime(screen_name=target_screen_name, created_at=now)

        for tweet in tweets:
            resp = twitter.post('statuses/update.json', data={'status':tweet.description})
            if not resp.status == 200:
                logging.debug('post error:' + str(tweet.tweet_id))
    return str(len(users))

@app.route('/diffupdate')
def diff_update():
    now = drop_seconds(datetime.datetime.utcnow())
    users = db.Query(User).fetch(1000)
    for user in users:
        tweets=[]
        if not user.last_tweet_id == None:
            g.user = user

            url = 'statuses/user_timeline.json?count=200&screen_name=' + user.target_screen_name + '&since_id=' + str(user.last_tweet_id)
            resp = selftwitter.get(url)

            if resp.status == 200 and len(resp.data) > 0:
               tweets = get_target_tweets(resp, now, user.turn_around_span_days)
            else:
                logging.debug('Unable to load tweets from Twitter. Maybe out of '
                              'API calls or Twitter is overloaded.')

            for tweet in tweets:
                push_tweet(tweet)

            user.last_tweet_id = Tweet.get_last_tweet_id(base_screen_name=user.name, target_screen_name=user.target_screen_name)
            db.put(user)
        
    return str(len(users))

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

@app.route('/user_initialize/<username>')
def user_initialize(username):
    user = User.get(username)
    g.user = user

    now = drop_seconds(datetime.datetime.utcnow())
    depth=0
    tweets=[]
    if user is not None:
        while depth < 7:
            depth += 1
            logging.debug(depth)

            url = 'statuses/user_timeline.json?count=200&screen_name=' + user.target_screen_name
            url += '&page=' + str(depth) if depth > 1 else ""

            resp = twitter.get(url)

            if resp.status == 200 and len(resp.data) > 0:
               extract_tweets = get_target_tweets(resp, now, user.turn_around_span_days)
               if len(extract_tweets) == 0: break

               tweets += extract_tweets
            else:
                logging.debug('Unable to load tweets from Twitter. Maybe out of '
                              'API calls or Twitter is overloaded.')
                break

    for tweet in tweets:
        push_tweet(tweet)
    user.last_tweet_id = Tweet.get_last_tweet_id(base_screen_name=user.name, target_screen_name=user.target_screen_name)
    db.put(user)

    return 'ok'


def push_tweet(tweet):
    if db.Query(Tweet).filter('base_screen_name = ', g.user.name).filter('tweet_id = ', int(tweet['id'])).fetch(1):
        logging.debug('duplicate tweet')
        return

    data = Tweet(tweet_id = int(tweet['id']),
                 base_screen_name = g.user.name,
                 screen_name = tweet['user']['screen_name'],
                 description = tweet['text'],
                 created_at = string_to_date(tweet['created_at'])
                 )
    db.put(data)
    return

def get_target_tweets(resp, now, daynum):
    tweets=[]
    pattern = re.compile("@([a-zA-Z0-9_]+)")
    for tweet in resp.data:
        tweet_date = string_to_date(tweet['created_at'])

        if now - tweet_date < datetime.timedelta(daynum):
            tweet['text'] = pattern.sub(".\\1",tweet['text'])
            tweets.append(tweet)
        else:
            break
    return tweets

def string_to_date(date_str):
    d = datetime.datetime.strptime(date_str,'%a %b %d %H:%M:%S +0000 %Y')
    return drop_seconds(d)

def drop_seconds(d):
    return datetime.datetime(d.year, d.month, d.day, d.hour, d.minute)

# set the secret key.  keep this really secret:
app.secret_key = 'the secret key'

if __name__ == '__main__':
    from wsgiref.handlers import CGIHandler
    CGIHandler().run(app)
