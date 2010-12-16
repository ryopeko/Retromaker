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
@twitter.tokengetter
def get_twitter_token():
    user = g.user
    if user is not None:
        return user.oauth_token, user.oauth_secret
    return None

@app.route('/cron/tweet')
def tweet():
    users = db.Query(User).filter('target_screen_name != ', None).fetch(1000)

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

@app.route('/cron/push_updatelist')
def push_updatelist():
    now = drop_seconds(datetime.datetime.utcnow())
    users = db.Query(User).filter('target_screen_name != ', None).fetch(1000)

    for user in users:
        taskqueue.add(url='/task/diff_update/' + user.name, method='GET')
        
    return str(len(users))

@app.route('/cron/clearning')
def clearning():
    users = db.Query(User).filter('target_screen_name != ', None).fetch(1000)

    for user in users:
        taskqueue.add(url='/task/clearner/' + user.name, method='GET')

    return 'ok'

def string_to_date(date_str):
    d = datetime.datetime.strptime(date_str,'%a %b %d %H:%M:%S +0000 %Y')
    return drop_seconds(d)

def drop_seconds(d):
    return datetime.datetime(d.year, d.month, d.day, d.hour, d.minute)

if __name__ == '__main__':
    from wsgiref.handlers import CGIHandler
    CGIHandler().run(app)
