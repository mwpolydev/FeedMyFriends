import urlparse
import time
import redis
import os
import postgres_db as pgdb
import logging


REDIS_CONN = os.environ.get('REDISTOGO_URL', 'redis://localhost:6379')

redis_url = urlparse.urlparse(REDIS_CONN)

#Default 3 hours per key
EXPIRATION_TIME = 3600*48

def make_unicode_safe(str, default_encoding = "utf-8"):
    return unicode(str, default_encoding) if type(str) == type("") else str

class FMFRedisHandler(redis.StrictRedis):

    def __init__(self, host, port, password, db=0):
        redis.StrictRedis.__init__(self, host=host, port=port, password=password, db=db)

    def _run_checks(self):
        """method to confirming essential keys are available"""
        pass

    def set_feed(self, feed_name):
        feed_mapping = {}
        create_time = time.time()
        feed_id_suffix = str(self.incr("feed_id_suffix", 1))
        feed_id = str(int(create_time//100))+"-"+feed_id_suffix
        feed_mapping['create_time'] = create_time
        feed_mapping['feed_name'] = feed_name
        feed_mapping['feed_id'] = feed_id

        resp = self.hmset('feed:'+feed_id, feed_mapping)

        self.zadd('feeds', 0, feed_name+"|"+feed_id)
        pgdb.set_feed(pgdb.PG_ENGINE, feed_id, feed_name, create_time)
        return feed_id

    def set_post(self, feed_id, post_dict):
        create_time = time.time()
        post_id_suffix = str(self.incr("post_id_suffix", 1))
        post_id = str(int(create_time//100))+"-"+post_id_suffix
        post_dict['post_id'] = post_id
        post_dict['create_time'] = create_time
        post_dict['feed_id'] = feed_id

        #TODO: need to simplify this step too much I/O!! Need to configure background tasks
        resp = self.hmset('post:'+post_id, post_dict)
        self.zadd('wall', create_time, post_id)
        pgdb.set_post(pgdb.PG_ENGINE, feed_id=post_dict['feed_id'],
                                      create_time=post_dict['create_time'],
                                      post_id=post_dict['post_id'],
                                      favicon_url = post_dict['favicon_url'],
                                      description = post_dict['description'],
                                      title = post_dict['title'],
                                      url = post_dict['url'])

        return self.hgetall('post:'+post_id)

    def get_wall(self, n=25):
        """return the n most recent post_id's for the wall"""
        resp = self.zrevrange('wall', 0, n-1)
        if not resp:
            posts = pgdb.get_wall(pgdb.PG_ENGINE, n)
            resp = []
            for post in posts:
                self.zadd('wall', post['create_time'], post['post_id'])
                resp.append(post['post_id'])
            self.expire('wall', EXPIRATION_TIME)
        return [self.get_post(post_id) for post_id in resp]

    def get_post(self, post_id):
        cache_post = self.hgetall('post:'+str(post_id))
        if cache_post:
            cache_post['description'] = make_unicode_safe(cache_post['description'])
            cache_post['title'] =  make_unicode_safe(cache_post['title'])
            return cache_post
        else:
            db_post = pgdb.get_post(pgdb.PG_ENGINE, post_id)
            self.hmset('post:'+post_id, db_post)
            return db_post

    def get_feed(self, feed_id):
        cache_feed = self.hgetall('feed:'+str(feed_id))
        if cache_feed:
            return cache_feed
        else:
            db_feed = pgdb.get_feed_by_id(pgdb.PG_ENGINE, feed_id)
            self.hmset('feed:'+feed_id, db_feed)
            return db_feed

    def get_all_feeds(self):
        feeds = self.zrangebylex('feeds', "-", "+")
        if feeds:
            return [self.get_feed(feed_id.split("|")[1]) for feed_id in feeds]
        else:
            feeds_from_db = pgdb.get_feeds(pgdb.PG_ENGINE)
            for feed in feeds_from_db:
                self.zadd('feeds', 0, feed['feed_name']+"|"+feed['feed_id'])
                self.hmset('feed:'+feed['feed_id'], feed)
            self.expire('feeds', EXPIRATION_TIME)
            return feeds_from_db

    def delete_post(self, post_id):
        self.delete('post:'+str(post_id))
        self.zrem('wall', str(post_id))
        deleted_db = pgdb.delete_post(pgdb.PG_ENGINE, str(post_id))
        return deleted_db

    def add_post_to_feed(self, post_id, feed_id):
        """Input: post_id str, feed_id str
           Output: the unique combination of feed_id|post_id
           If the post already exists in the feeds list then it returns the score(create time) from cache
           Otherwise it creates the record in the PGDB and return the unique id after adding to the cache
        """
        key = 'feed_posts:'+feed_id
        if self.zscore(key, post_id):
            print('hit cache')
            return feed_id+"|"+post_id
        else:
            print('hit db')
            self.zadd(key, time.time(), post_id)
            res = pgdb.add_post_to_feed(pgdb.PG_ENGINE, post_id, feed_id)
            return res[0]


    def get_posts_by_feed(self, feed_id, min_time=0.0, max_time=float('inf')):
        """
        :param feed_id:
        :param min_time:
        :param max_time:
        :return: A list of dictionaries representing the 100 Most recent posts associated to a given feed
        """
        #TODO: Need to make the calculation iterative as the number of posts grows
        key = 'feed_posts:'+str(feed_id)
        if self.exists(key):
            print("hit cache")
            return [self.get_post(post_id) for post_id in self.zrevrangebyscore(key, max_time, min_time)]
        else:
            print("hit db")
            results = pgdb.get_n_most_recent_posts_by_feed(pgdb.PG_ENGINE,
                                                           feed_id,
                                                           ub_time = max_time,
                                                           n=100)
            output = []
            for row in results:
                #function adds the top 25 records to the results, but only outputs results
                #between the min and max time
                self.zadd(key, row['create_time'], row['post_id'])
                if min_time <= row['create_time'] <= max_time:
                    output.append(self.get_post(row['post_id']))
            self.expire(key, EXPIRATION_TIME)
            return output


if __name__ == "__main__":
    redis_url = urlparse.urlparse(os.environ.get('REDISTOGO_URL', 'redis://localhost:6379'))
    rs = FMFRedisHandler(host=redis_url.hostname, port=redis_url.port, db=0, password=redis_url.password)
    print rs.get_posts_by_feed('test_id9', 1418370691, 1418370691.468)









