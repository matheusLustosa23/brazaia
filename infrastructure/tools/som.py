"""Tools de SOM nos devices: gravar o microfone, tocar um áudio (ou bipe/alarme) e o volume.
Rodam NO DEVICE (companion/tools/som_handler.py) — aqui só valida, conversa com o device e guarda a gravação."""
import base64
import json
import os
from typing import Literal

from pydantic import BaseModel, Field

from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.storage.file_store import FileStore


async def _checar(gateway: DeviceGateway, device: str, handler: str) -> str | None:
    """Motivo pra NÃO chamar (offline / companion antigo sem essa função) ou None."""
    conectados = gateway.connections.names()
    if device not in conectados:
        return (f"o device '{device}' está offline — conectados agora: "
                + (", ".join(conectados) or "nenhum") + ".")
    caps = await gateway.capabilities(device)
    if caps is not None and handler not in caps:
        return f"o companion do '{device}' ainda não tem essa função (ele se atualiza na próxima reconexão)."
    return None


def formato_audio(dados: bytes) -> tuple[str, str]:
    """(extensão, mime) pelo CONTEÚDO: o Termux grava MP4/M4A ou AAC puro (ADTS) conforme a versão."""
    if dados[4:8] == b"ftyp":
        return ".m4a", "audio/mp4"
    if dados[:2] in (b"\xff\xf1", b"\xff\xf9"):
        return ".aac", "audio/aac"
    return ".aac", "audio/aac"


def guardar_gravacao(store: FileStore, resposta: str, device: str, session: str) -> tuple[str, bytes, str, dict]:
    """Resposta do device (JSON com o áudio) → file_id. Usado pela tool e pelo painel."""
    d = json.loads(resposta)
    dados = base64.b64decode(d["audio_b64"])
    ext, mime = formato_audio(dados)
    fid = store.put(dados, device=device, session=session, kind="audio", ext=ext,
                    title=f"gravação de {d['segundos']} s no {device}")
    return fid, dados, mime, d


_DEVICE = Field(description="Em qual device (ex.: 'S24' = o celular que anda com o dono). Use o que ele pediu.")


class RecordAudioInput(BaseModel):
    device: str = _DEVICE
    acao: Literal["gravar", "iniciar", "parar", "status"] = Field(default="gravar", description=(
        "gravar = por N segundos e já devolve · iniciar = começa SEM tempo (até pedirem pra parar; máx. 30 min) · "
        "parar = encerra a gravação iniciada e guarda · status = se há gravação em andamento."))
    segundos: int = Field(default=10, ge=1, le=300, description="Só com acao=gravar: 1 a 300 s.")


class RecordAudioTool(Tool[RecordAudioInput]):
    name = "record_audio"
    description = (
        "GRAVA o microfone de um device e guarda o áudio (volta um file_id). "
        "Ex.: 'grava 30 segundos no celular' → record_audio(device='S24', segundos=30) · 'começa a gravar a "
        "reunião' → record_audio(device='S24', acao='iniciar') · 'para a gravação' → record_audio(device='S24', "
        "acao='parar'). Erro ou timeout do device = relate e NÃO repita a mesma chamada no turno. "
        "Se o Android bloquear o microfone (tela apagada), o resultado diz — não invente que gravou."
    )
    input_schema = RecordAudioInput
    side = "server"
    action_class = "reversible"
    timeout_s = 340.0
    router_hint = "gravar áudio do microfone do celular"

    def __init__(self, gateway: DeviceGateway, store: FileStore) -> None:
        self._gw, self._store = gateway, store

    async def run(self, p: RecordAudioInput, ctx: ToolCtx) -> str:
        if motivo := await _checar(self._gw, p.device, "record_audio"):
            return f"[erro] {motivo}"
        espera = {"gravar": p.segundos + 30, "parar": 120}.get(p.acao, 30)
        r = await self._gw.request(p.device, "record_audio", {"acao": p.acao, "segundos": p.segundos}, timeout=espera)
        if not isinstance(r, str) or not r.startswith("{"):
            return r if isinstance(r, str) else "[erro] o device não respondeu"
        fid, _, _, d = guardar_gravacao(self._store, r, p.device, ctx.session_id)
        return f"[áudio gravado] {self._store.marker(fid)} · {d['segundos']} s · {d['bytes'] // 1024} KB"


class PlayAudioInput(BaseModel):
    device: str = _DEVICE
    som: Literal["bipe", "alarme", "arquivo"] = Field(default="bipe", description=(
        "bipe = 3 bipes curtos · alarme = toque longo e alto (achar o celular) · arquivo = um áudio guardado (file_id)."))
    file_id: str | None = Field(default=None, description="Só com som=arquivo: o file_id de um áudio que JÁ apareceu na conversa.")


class PlayAudioTool(Tool[PlayAudioInput]):
    name = "play_audio"
    description = (
        "TOCA um som no device: bipe, alarme (pra achar o celular — junte com set_volume no máximo) ou um "
        "áudio guardado (file_id, ex.: uma gravação). Música do Spotify NÃO é aqui — é a tool spotify.\n"
        "Ex.: 'faz meu celular tocar, não acho ele' → set_volume(device='S24', canal='musica', acao='maximo') e "
        "play_audio(device='S24', som='alarme')."
    )
    input_schema = PlayAudioInput
    side = "server"
    action_class = "reversible"
    timeout_s = 60.0
    router_hint = "tocar bipe/alarme ou um áudio no celular"

    def __init__(self, gateway: DeviceGateway, store: FileStore) -> None:
        self._gw, self._store = gateway, store

    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        if args.get("som") == "arquivo" and not args.get("file_id"):
            return GuardResult(ok=False, reason="qual áudio? (preciso do file_id de um áudio que já apareceu)")
        return GuardResult(ok=True)

    async def run(self, p: PlayAudioInput, ctx: ToolCtx) -> str:
        if motivo := await _checar(self._gw, p.device, "play_audio"):
            return f"[erro] {motivo}"
        args: dict = {"som": p.som}
        if p.som == "arquivo":
            dados = self._store.read_bytes(p.file_id or "")
            if dados is None:
                return f"[erro] o áudio '{p.file_id}' não existe — não invente ids."
            args = {"audio_b64": base64.b64encode(dados).decode(),
                    "ext": os.path.splitext(self._store.path(p.file_id or "") or ".aac")[1]}
        return await self._gw.request(p.device, "play_audio", args, timeout=50)


class SetVolumeInput(BaseModel):
    device: str = _DEVICE
    canal: Literal["musica", "toque", "notificacao", "alarme", "chamada", "sistema"] = Field(default="musica", description=(
        "Qual volume: musica (mídia/Spotify/fone) · toque (ligação/campainha) · notificacao · alarme · chamada · sistema."))
    acao: Literal["definir", "aumentar", "diminuir", "maximo", "mudo", "consultar"] = Field(default="definir", description=(
        "definir (use nivel) · aumentar/diminuir (~20% por vez) · maximo · mudo · consultar (só lê)."))
    nivel: int | None = Field(default=None, ge=0, le=100, description="Só com acao=definir: 0 a 100 (%).")


class SetVolumeTool(Tool[SetVolumeInput]):
    name = "set_volume"
    description = (
        "Volume do celular por canal. 'aumenta o volume' → set_volume(device='S24', acao='aumentar') · "
        "'volume 70' → acao='definir', nivel=70 · 'tira do silencioso' → canal='toque', acao='definir', nivel=70 "
        "(se o celular estiver no modo silencioso o Android pode manter mudo — o resultado diz o valor real)."
    )
    input_schema = SetVolumeInput
    side = "server"
    action_class = "reversible"
    timeout_s = 30.0
    router_hint = "aumentar, baixar, consultar volume ou tirar do silencioso o celular"

    def __init__(self, gateway: DeviceGateway) -> None:
        self._gw = gateway

    async def run(self, p: SetVolumeInput, ctx: ToolCtx) -> str:
        if motivo := await _checar(self._gw, p.device, "set_volume"):
            return f"[erro] {motivo}"
        acao = None if p.acao == "consultar" else p.acao
        return await self._gw.request(p.device, "set_volume",
                                      {"canal": p.canal, "acao": acao or "definir", "nivel": None if acao is None else p.nivel},
                                      timeout=25)
