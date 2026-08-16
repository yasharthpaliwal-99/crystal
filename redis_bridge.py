import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)


def publish_raw(stream: str, fields: dict):
    r.xadd(stream, fields)