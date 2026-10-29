import os, base64, hashlib, pprint
from infrastructure.vision.image_index import ImageIndex

MAX_IMG_PIXELS = 900_000   # área (w*h). Acima de ~1M o Qwen3VLProcessor gera >1023 tokens de imagem,
                           # a tokenização trunca e dá 400. Medido: 1120x840 passa; 1024x1024 falha → cap 900K.
_WEB_SAFE = ("image/jpeg", "image/png", "image/webp")

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
            
                

def normalize_image_uri(url: str, max_pixels: int = MAX_IMG_PIXELS) -> str:
    """Deixa a imagem pronta pro vLLM: reduz ÁREA > max_pixels (mantém aspecto, evita o 400) e
    converte formato não web-safe pra JPEG. Idempotente p/ jpeg/png/webp pequenos. Em erro devolve a url original."""
    if not isinstance(url, str) or not url.startswith("data:image/"):
        return url
    try:
        import cv2, numpy as np
        mime = url[5:].split(";", 1)[0].split(",", 1)[0].lower()
        b64 = url.split(",", 1)[1] if "," in url else url
        buf = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            return url
        h, w = img.shape[:2]
        grande = w * h > max_pixels
        if not grande and mime in _WEB_SAFE:
            return url
        if grande:
            esc = (max_pixels / (w * h)) ** 0.5
            img = cv2.resize(img, (max(1, int(w * esc)), max(1, int(h * esc))), interpolation=cv2.INTER_AREA)
        ok, out = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return url
        return "data:image/jpeg;base64," + base64.b64encode(out).decode()
    except Exception:
        return url
