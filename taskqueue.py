from flask import Flask, redirect, url_for, request, render_template, abort, flash, get_flashed_messages, session, g
from flaskext.oauth import OAuth
app = Flask(__name__)

from google.appengine.ext import db
from google.appengine.api import users, taskqueue
import logging
import datetime
import time
import re

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

@twitter.tokengetter
def get_twitter_token():
    user = g.user
    if user is not None:
        return user.oauth_token, user.oauth_secret
    return None

@selftwitter.tokengetter
def selftoken():
    return conf.oauth_token, conf.oauth_secret

@app.route('/task/user_initialize/<username>')
def user_initialize(username):
    user = User.get(username)
    if user is None:
        return abort(500)

    g.user = user

    now = drop_seconds(datetime.datetime.utcnow())
    depth=0
    tweets=[]

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


@app.route('/task/diff_update/<username>')
def diff_update(username):
    user = User.get(username)
    if user is None: return 'ng'

    g.user = user

    now = drop_seconds(datetime.datetime.utcnow())

    url = 'statuses/user_timeline.json?count=200&screen_name=' + user.target_screen_name + '&since_id=' + str(user.last_tweet_id)
    resp = selftwitter.get(url)

    tweets=[]
    if resp.status == 200 and len(resp.data) > 0:
        tweets = get_target_tweets(resp, now, user.turn_around_span_days)
    else:
        logging.debug('Unable to load tweets from Twitter. Maybe out of '
                      'API calls or Twitter is overloaded.')

    for tweet in tweets:
        push_tweet(tweet)

    user.last_tweet_id = Tweet.get_last_tweet_id(base_screen_name=user.name, target_screen_name=user.target_screen_name)
    db.put(user)
    return 'ok'

def push_tweet(tweet):
    if Tweet.tweet_exist(base_screen_name=g.user.name,tweet_id=tweet['id']):
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

if __name__ == '__main__':
    from wsgiref.handlers import CGIHandler
    CGIHandler().run(app)
