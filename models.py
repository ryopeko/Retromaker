import datetime
from google.appengine.ext import db

class User(db.Model):
    name = db.StringProperty()
    twitter_id = db.IntegerProperty()
    target_screen_name = db.StringProperty()
    turn_around_span_days = db.IntegerProperty()
    last_tweet_id = db.IntegerProperty()
    oauth_token = db.StringProperty()
    oauth_secret = db.StringProperty()

    @classmethod
    def get(self, name):
        query = User.all()
        query.filter('name =', name)
        return query.get()

class Tweet(db.Model):
    tweet_id = db.IntegerProperty()
    base_screen_name = db.StringProperty()
    screen_name = db.StringProperty()
    description = db.TextProperty()
    created_at = db.DateTimeProperty()

    @classmethod
    def get(self, retro_user_id):
        query = Tweet.all()
        query.filter('retro_user_id = ', int(retro_user_id))
        return query.fetch(0)

    @classmethod
    def get_by_datetime(self, screen_name, created_at):
        query = db.Query(Tweet)
        query.filter('screen_name = ', screen_name)
        query.filter('created_at = ', created_at)
        query.order('tweet_id')
        return query.fetch(1000)

    @classmethod
    def find_by_1day_schedule(self, base_screen_name, screen_name, span):
        query = db.Query(Tweet)
        query.filter('base_screen_name = ', base_screen_name)
        query.filter('screen_name = ', screen_name)
        query.filter('created_at > ', drop_seconds(datetime.datetime.utcnow()) - datetime.timedelta(days=span))
        query.filter('created_at < ', drop_seconds(datetime.datetime.utcnow()) - datetime.timedelta(days=span) + datetime.timedelta(days=1))
        query.order('created_at')
        query.order('tweet_id')
        return query.fetch(10000)

    @classmethod
    def get_last_tweet_id(self, base_screen_name, target_screen_name):
        query = db.Query(Tweet)
        query.filter('base_screen_name = ', base_screen_name)
        query.filter('screen_name = ', target_screen_name)
        query.order('-tweet_id')
        return query.get().tweet_id

class UserInit(db.Model):
    name = db.StringProperty()
    created_at = db.DateTimeProperty()
    reset = db.BooleanProperty()

def drop_seconds(d):
    return datetime.datetime(d.year, d.month, d.day, d.hour, d.minute)
