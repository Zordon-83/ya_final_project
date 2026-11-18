from .auth import router as auth_router
from .booking import router as booking_router
from .health import router as health_router
from .users import router as users_router

__all__ = ['auth_router', 'booking_router', 'health_router', 'users_router']
