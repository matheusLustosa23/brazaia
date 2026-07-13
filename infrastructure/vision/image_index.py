class ImageIndex:
    def __init__(self) -> None:
        self._map: dict[str, str] = {}
    def put(self, img_id: str, path: str) -> str | None:
        self._map[img_id] = path
    def get(self, img_id: str) -> str | None:
        return self._map.get(img_id)