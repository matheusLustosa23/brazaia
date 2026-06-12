
class AgentError(Exception):
    """Raiz das exceções de domínio. Pura — domain/ não importa FastAPI.
    register_exception_handlers mapeia isto -> ApiResponse.error(status, message)."""
    status: int = 500
    message: str = 'erro interno do agente'
    
    def __init__(self, message:str = None, *, status:int = None):

        if message is not None:
            self.message = message
        if status is not None:
            self.status = status
        
        super().__init__(self.message)
        
        
                
            
                
        
       

    