try:
    import orjson
    def dumps(x) -> str: return orjson.dumps(x).decode()
    def loads(x): return orjson.loads(x)
except ImportError:
    import json
    def dumps(x) -> str: return json.dumps(x)
    def loads(x): return json.loads(x)