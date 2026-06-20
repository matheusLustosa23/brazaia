import uuid

class InMemorySessionStore:
    
    def __init__(self):
        self._data: dict[str,list[dict]] = {}
    
    def create(self) -> str:
        sid = uuid.uuid4().hex
        self._data[sid] = []
        return sid
    
    def get(self, session_id: str) -> list[dict]:
        return self._data.setdefault(session_id, [])
    
    def set(self, session_id: str, history: list[dict]) -> None:
        self._data[session_id] = history
    
    def append(self, session_id: str, message: dict) -> None:
        self._data.setdefault(session_id, []).append(message)
    

class SqlLiteSessionStore:
    """Esqueleto — persistência real para feat/session."""
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
    
    def create(self) -> str:
        raise NotImplementedError

    def get(self, session_id: str) -> list[dict]:
        raise NotImplementedError
    
    def set(self, session_id: str, history: list[dict]) -> None:
        raise NotImplementedError

    def append(self, session_id: str, message: dict) -> None:
        raise NotImplementedError