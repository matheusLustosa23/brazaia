import os, base64, hashlib, pprint
from infrastructure.vision.image_index import ImageIndex

def _img_id(url: str) -> str:
    b64 = url.split(",", 1)[1] if "," in url else url
    return hashlib.sha256(b64.encode()).hexdigest()[:12]        # id determinístico (hash do conteúdo)

def _save_image(url: str, session_id: str, device_id: str | None, img_id: str, index: ImageIndex) -> None:
    dev = device_id or "server"                                 # chat sem device → "server"
    outdir = os.path.expanduser(f"~/brazaia/{dev}/{session_id}")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{img_id}.jpg")
    b64 = url.split(",", 1)[1] if "," in url else url
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))
    index.put(img_id, path)

def _has_image(history: list[dict]) -> bool:
    return any(
        isinstance(m.get("content"), list) 
            and 
        any(
            isinstance(b, dict) and b.get("type") == "image_url"
            for b in m["content"]
        )
        for m in history
    )

def _strip(history: list[dict]) -> list[dict]:
    
    if _has_image(history):
        for message in history:
            content = message.get("content")
            if  isinstance(content, list): 
                message["content"] = [
                    block 
                    for block in content
                    if not (isinstance(block, dict) and block.get("type") == "image_url")
                ]
    
    return history

def persist_image(url: str, session_id: str, device_id: str | None, index: ImageIndex) -> str:
    """data URI -> disco + image_index. Idempotente (id = hash do conteúdo). Devolve o id."""
    _id = _img_id(url)
    _save_image(url, session_id, device_id, _id, index)
    return _id             
            
                
            
  