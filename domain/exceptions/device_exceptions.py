from domain.exceptions.base import AgentError

class DeviceOffline(AgentError):
    status = 503
    message = "device offline ou não conectado"